import asyncio
import csv
import logging
import os
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters


ROOT = Path(__file__).resolve().parent
LABELS_PATH = ROOT / "labels.csv"
SPLITS = ("train", "val", "test")
ALLOWED_USER_ID = 1494239915
MENU = ReplyKeyboardMarkup(
    [["Train", "Val", "Test"], ["Status", "Sync"]], resize_keyboard=True
)


def read_labels(path):
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file, skipinitialspace=True)
        if not rows.fieldnames or not {"id", "label"} <= set(rows.fieldnames):
            raise ValueError(f"{path} must contain id and label columns")
        labels = {}
        for row in rows:
            if row["id"] in labels:
                raise ValueError(f"duplicate label id: {row['id']}")
            labels[row["id"]] = row["label"]
        return labels


class LabelBot:
    def __init__(self, hf_token):
        self.api = HfApi(token=hf_token)
        self.repo_id = f"{self.api.whoami()['name']}/oldmoney"
        self.rows = {}
        self.by_prefix = {}
        self.labels = {}
        self.split = "val"
        self.positions = {split: 0 for split in SPLITS}
        self.history = []
        self.pending = 0
        self.sync_task = None
        self.lock = asyncio.Lock()
        self.load_data(hf_token)

    def load_data(self, token):
        for split in SPLITS:
            path = ROOT / f"dataset_{split}.csv"
            if not path.is_file():
                path = Path(hf_hub_download(
                    self.repo_id, path.name, repo_type="dataset", token=token
                ))
            with path.open(encoding="utf-8-sig", newline="") as file:
                self.rows[split] = list(csv.DictReader(file))

        local = read_labels(LABELS_PATH)
        try:
            remote_path = Path(hf_hub_download(
                self.repo_id, "labels.csv", repo_type="dataset", token=token
            ))
            remote = read_labels(remote_path)
        except EntryNotFoundError:
            remote = {}
        conflicts = {key for key in local.keys() & remote if local[key] != remote[key]}
        if conflicts:
            raise ValueError(f"local and remote labels conflict for {len(conflicts)} images")
        self.labels = remote | local
        for row in (row for split in SPLITS for row in self.rows[split]):
            prefix = row["id"][:12]
            if prefix in self.by_prefix and self.by_prefix[prefix]["id"] != row["id"]:
                raise ValueError(f"non-unique image id prefix: {prefix}")
            self.by_prefix[prefix] = row
        self.save_labels()
        self.pending = int(self.labels != remote)

    def save_labels(self):
        temporary = LABELS_PATH.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["id", "label"])
            writer.writerows(sorted(self.labels.items()))
        temporary.replace(LABELS_PATH)

    def allowed(self, update):
        return bool(update.effective_user and update.effective_user.id == ALLOWED_USER_ID)

    def progress(self, split):
        rows = self.rows[split]
        return sum(row["id"] in self.labels for row in rows), len(rows)

    def next_row(self):
        rows = self.rows[self.split]
        for _ in rows:
            position = self.positions[self.split] % len(rows)
            self.positions[self.split] += 1
            if rows[position]["id"] not in self.labels:
                return rows[position]
        return None

    def image_buttons(self, row):
        prefix = row["id"][:12]
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Old money", callback_data=f"label|old_money|{prefix}"),
                InlineKeyboardButton("Not old money", callback_data=f"label|not_old_money|{prefix}"),
            ],
            [
                InlineKeyboardButton("Skip", callback_data=f"skip|{prefix}"),
                InlineKeyboardButton("Undo", callback_data="undo"),
            ],
        ])

    async def show_next(self, message):
        row = self.next_row()
        labelled, total = self.progress(self.split)
        if row is None:
            await message.reply_text(
                f"{self.split.title()} complete: {labelled}/{total}", reply_markup=MENU
            )
            return
        caption = (
            f"{self.split.title()}: {labelled}/{total}\n"
            f"{row.get('product_name', '')[:160]}\n{row.get('source', '')}"
        )
        buttons = self.image_buttons(row)
        try:
            await message.reply_photo(row["image_url"], caption=caption, reply_markup=buttons)
        except TelegramError:
            await message.reply_text(
                f"{caption}\n{row['image_url']}", reply_markup=buttons
            )

    async def status(self, message):
        lines = [
            f"{split.title()}: {labelled}/{total}"
            for split in SPLITS
            for labelled, total in [self.progress(split)]
        ]
        state = "pending upload" if self.pending else "synced"
        await message.reply_text("\n".join([*lines, f"Hugging Face: {state}"]), reply_markup=MENU)

    async def record(self, image_id, label):
        async with self.lock:
            previous = self.labels.get(image_id)
            if previous == label:
                return
            self.history.append((image_id, previous))
            self.labels[image_id] = label
            self.save_labels()
            self.pending += 1
        return await self.schedule_sync()

    async def undo(self):
        async with self.lock:
            if not self.history:
                return False
            image_id, previous = self.history.pop()
            if previous is None:
                self.labels.pop(image_id, None)
            else:
                self.labels[image_id] = previous
            self.save_labels()
            self.pending += 1
        error = await self.schedule_sync()
        return True, error

    async def schedule_sync(self):
        if self.pending >= 10:
            try:
                await self.sync()
            except Exception as error:
                logging.exception("batch Hugging Face sync failed")
                return error
            return None
        if self.sync_task:
            self.sync_task.cancel()
        self.sync_task = asyncio.create_task(self.delayed_sync())
        return None

    async def delayed_sync(self):
        try:
            await asyncio.sleep(60)
            await self.sync()
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("automatic Hugging Face sync failed")

    async def sync(self):
        task = self.sync_task
        if task and task is not asyncio.current_task():
            task.cancel()
        self.sync_task = None
        async with self.lock:
            if not self.pending:
                return
            await asyncio.to_thread(
                self.api.upload_file,
                path_or_fileobj=LABELS_PATH,
                path_in_repo="labels.csv",
                repo_id=self.repo_id,
                repo_type="dataset",
                commit_message=f"Update {self.pending} labels",
            )
            self.pending = 0

    async def start(self, update, context):
        if not self.allowed(update):
            return
        await update.effective_message.reply_text(
            "Choose a split or label the next validation image.", reply_markup=MENU
        )
        await self.show_next(update.effective_message)

    async def menu(self, update, context):
        if not self.allowed(update):
            return
        text = update.effective_message.text.lower()
        if text in SPLITS:
            self.split = text
            await self.show_next(update.effective_message)
        elif text == "status":
            await self.status(update.effective_message)
        elif text == "sync":
            await self.sync_reply(update.effective_message)

    async def command(self, update, context):
        if not self.allowed(update):
            return
        command = update.effective_message.text.split()[0][1:].split("@")[0]
        if command in SPLITS:
            self.split = command
            await self.show_next(update.effective_message)
        elif command == "status":
            await self.status(update.effective_message)
        elif command == "sync":
            await self.sync_reply(update.effective_message)

    async def sync_reply(self, message):
        try:
            await self.sync()
            await message.reply_text("Labels synced.", reply_markup=MENU)
        except Exception as error:
            logging.exception("manual Hugging Face sync failed")
            await self.sync_error(message, error)

    async def sync_error(self, message, error):
        retry = InlineKeyboardMarkup([
            [InlineKeyboardButton("Retry sync", callback_data="sync")]
        ])
        await message.reply_text(f"Sync failed: {error}", reply_markup=retry)

    async def callback(self, update, context):
        query = update.callback_query
        if not self.allowed(update):
            await query.answer()
            return
        await query.answer()
        data = query.data.split("|")
        try:
            await query.edit_message_reply_markup(None)
        except TelegramError:
            pass
        if data[0] == "label":
            row = self.by_prefix[data[2]]
            error = await self.record(row["id"], data[1])
            if error:
                await self.sync_error(query.message, error)
            await self.show_next(query.message)
        elif data[0] == "skip":
            await self.show_next(query.message)
        elif data[0] == "undo":
            undone = await self.undo()
            if not undone:
                await query.message.reply_text("Nothing to undo.", reply_markup=MENU)
            elif undone[1]:
                await self.sync_error(query.message, undone[1])
            await self.show_next(query.message)
        elif data[0] == "sync":
            await self.sync_reply(query.message)

    async def post_init(self, application):
        await application.bot.set_my_commands([
            BotCommand("start", "Open labeling controls"),
            BotCommand("train", "Label training images"),
            BotCommand("val", "Label validation images"),
            BotCommand("test", "Label test images"),
            BotCommand("status", "Show labeling progress"),
            BotCommand("sync", "Upload labels now"),
        ])
        if self.pending:
            await self.schedule_sync()

    async def post_shutdown(self, application):
        if self.sync_task:
            self.sync_task.cancel()
        if self.pending:
            try:
                await self.sync()
            except Exception:
                logging.exception("shutdown Hugging Face sync failed")


def main():
    logging.basicConfig(level=logging.INFO)
    token = os.environ["BOT_TOKEN"]
    bot = LabelBot(os.environ["HF_TOKEN"])
    application = (
        Application.builder().token(token).post_init(bot.post_init)
        .post_shutdown(bot.post_shutdown).build()
    )
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler([*SPLITS, "status", "sync"], bot.command))
    application.add_handler(CallbackQueryHandler(bot.callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.menu))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
