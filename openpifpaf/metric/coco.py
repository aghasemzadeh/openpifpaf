import logging
import json
import zipfile

import numpy as np

from .base import Base

try:
    import pycocotools.coco
    from pycocotools.cocoeval import COCOeval
    # monkey patch for Python 3 compat
    pycocotools.coco.unicode = str
except ImportError:
    pass

LOG = logging.getLogger(__name__)


class Coco(Base):
    def __init__(self, coco, *,
                 max_per_image=20,
                 category_ids=None,
                 iou_type='keypoints',
                 small_threshold=0.0):
        super().__init__()

        if category_ids is None:
            category_ids = [1]

        self.coco = coco
        self.max_per_image = max_per_image
        self.category_ids = category_ids
        self.iou_type = iou_type
        self.small_threshold = small_threshold

        self.predictions = []
        self.image_ids = []
        self.eval = None
        self.decoder_time = 0.0
        self.nn_time = 0.0

        LOG.debug('max = %d, category ids = %s, iou_type = %s',
                  self.max_per_image, self.category_ids, self.iou_type)

    def _stats(self, predictions=None, image_ids=None):
        # from pycocotools.cocoeval import COCOeval
        if predictions is None:
            predictions = self.predictions
        if image_ids is None:
            image_ids = self.image_ids

        coco_eval = self.coco.loadRes(predictions)

        self.eval = COCOeval(self.coco, coco_eval, iouType=self.iou_type)
        LOG.info('cat_ids: %s', self.category_ids)
        if self.category_ids:
            self.eval.params.catIds = self.category_ids

        if image_ids is not None:
            print('image ids', image_ids)
            self.eval.params.imgIds = image_ids
        self.eval.evaluate()
        self.eval.accumulate()
        self.eval.summarize()
        return self.eval.stats

    def accumulate(self, predictions, image_meta):
        image_id = int(image_meta['image_id'])
        self.image_ids.append(image_id)

        if self.small_threshold:
            predictions = [pred for pred in predictions
                           if pred.scale(v_th=0.01) >= self.small_threshold]
        if len(predictions) > self.max_per_image:
            predictions = predictions[:self.max_per_image]

        image_annotations = []
        for pred in predictions:
            pred_data = pred.json_data()
            pred_data['image_id'] = image_id
            pred_data = {
                k: v for k, v in pred_data.items()
                if k in ('category_id', 'score', 'keypoints', 'bbox', 'image_id')
            }
            image_annotations.append(pred_data)

        # force at least one annotation per image (for pycocotools)
        if not image_annotations:
            image_annotations.append({
                'image_id': image_id,
                'category_id': 1,
                'keypoints': np.zeros((17*3,)).tolist(),
                'bbox': [0, 0, 1, 1],
                'score': 0.001,
            })

        if LOG.getEffectiveLevel() == logging.DEBUG:
            self._stats(image_annotations, [image_id])
            LOG.debug(image_meta)

        self.predictions += image_annotations

    def write_predictions(self, filename):
        predictions = [
            {k: v for k, v in annotation.items()
             if k in ('image_id', 'category_id', 'keypoints', 'score')}
            for annotation in self.predictions
        ]
        with open(filename + '.pred.json', 'w') as f:
            json.dump(predictions, f)
        LOG.info('wrote %s.pred.json', filename)
        with zipfile.ZipFile(filename + '.zip', 'w') as myzip:
            myzip.write(filename + '.pred.json', arcname='predictions.json')
        LOG.info('wrote %s.zip', filename)

    def stats(self):
        n_images = len(self.image_ids)

        data = {
            'stats': self._stats().tolist(),
            'n_images': n_images,
            'decoder_time': self.decoder_time,
            'nn_time': self.nn_time,
        }

        return data