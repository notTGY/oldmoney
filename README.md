# oldmoney

Algorithm to solve whether or not 
you are old money.

## Plan

1. parse 6-7 fashion online stores,
retrieve all photos with full looks.
2. create initial dataset of photos.
3. annotate 15% of dataset
if photo is relevant (we can see enough of
the outfit, it is displayed on person)
4. train decision tree over scores
collected from siglip2 ran
on multiple prompts (pos+neg) on each image.
5. filter out irrelevant pics by inferring model.
6. annotate 20% of left data
for validation and test.
7. train decision tree for old money
classification on validation split.
8. test on test.
9. infer on train.
10. we have pseudo labelled dataset,
now we do a manual pass over train to
second check labels.
(we prioritize based on heruistics
observed on test)
11. we have labelled dataset.
12. finetune dinov2-small and report test.