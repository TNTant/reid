from __future__ import print_function
import time
from collections import OrderedDict

import torch
from torch import nn
from torch.autograd import Variable

from .database import FeatureDatabase
from ..utils.meters import AverageMeter


class _ModelWrapper(nn.Module):
    def __init__(self, model, layer_names=None):
        super(_ModelWrapper, self).__init__()
        if layer_names is None:
            layer_names = []
        self.model = model
        self.layer_names = set(layer_names)

    def forward(self, x):
        if len(self.layer_names) == 0:
            return self.model(x)
        # TODO: Check register_forward_hook
        outs = {}
        for name, module in self.model._modules.items():
            if isinstance(module, nn.Linear):
                x = x.view(x.size(0), -1)
            x = module(x)
            if name in self.layer_names:
                outs[name] = x
        return outs


def extract_features(model, data_loader, output_file=None, print_freq=1):
    # TODO: Support extract features from multiple layers
    model.eval()
    wrapper = _ModelWrapper(model)

    features = OrderedDict() if output_file is None else \
        FeatureDatabase(output_file, 'w')

    batch_time = AverageMeter()
    data_time = AverageMeter()

    end = time.time()
    for i, (imgs, fnames, _, _) in enumerate(data_loader):
        data_time.update(time.time() - end)

        inputs = Variable(imgs, volatile=True)
        outputs = wrapper(inputs).data.cpu()
        if output_file is not None:
            outputs = outputs.numpy()

        for fname, output in zip(fnames, outputs):
            features[fname] = output

        batch_time.update(time.time() - end)
        end = time.time()

        if (i + 1) % print_freq == 0:
            print('Extract Features: [{}/{}]\t'
                  'Time {:.3f} ({:.3f})\t'
                  'Data {:.3f} ({:.3f})\t'.format(
                  i + 1, len(data_loader),
                  batch_time.val, batch_time.avg,
                  data_time.val, data_time.avg))

    if output_file is None:
        return features

    features.close()


def extract_embeddings(model, data_loader, print_freq=1):
    model.eval()

    embeddings = []

    batch_time = AverageMeter()
    data_time = AverageMeter()

    end = time.time()
    for i, inputs in enumerate(data_loader):
        data_time.update(time.time() - end)

        inputs = [Variable(x, volatile=True) for x in inputs]
        outputs = model(*inputs).data
        embeddings.append(outputs)

        batch_time.update(time.time() - end)
        end = time.time()

        if (i + 1) % print_freq == 0:
            print('Extract Embedding: [{}/{}]\t'
                  'Time {:.3f} ({:.3f})\t'
                  'Data {:.3f} ({:.3f})\t'.format(
                  i + 1, len(data_loader),
                  batch_time.val, batch_time.avg,
                  data_time.val, data_time.avg))

    return torch.cat(embeddings)
