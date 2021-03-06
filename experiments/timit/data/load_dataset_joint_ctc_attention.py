#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Load dataset for the Joint CTC-Attention model (TIMIT corpus).
   In addition, frame stacking and skipping are used.
   You can use only the single GPU version.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join
import pickle
import numpy as np

from utils.progressbar import wrap_iterator
from utils.dataset.all_load.joint_ctc_attention_all_load import DatasetBase
from utils.io.inputs.frame_stacking import stack_frame


class Dataset(DatasetBase):

    def __init__(self, data_type, label_type, batch_size, eos_index,
                 max_epoch=None, splice=1,
                 num_stack=1, num_skip=1,
                 shuffle=False, sort_utt=False, sort_stop_epoch=None,
                 progressbar=False):
        """A class for loading dataset.
        Args:
            data_type (string): train or dev or test
            label_type (string): stirng, phone39 or phone48 or phone61 or
                character or character_capital_divide
            batch_size (int): the size of mini-batch
            eos_index (int): the index of <EOS> class
            max_epoch (int, optional): the max epoch. None means infinite loop.
            splice (int, optional): frames to splice. Default is 1 frame.
            num_stack (int, optional): the number of frames to stack
            num_skip (int, optional): the number of frames to skip
            shuffle (bool, optional): if True, shuffle utterances. This is
                disabled when sort_utt is True.
            sort_utt (bool, optional): if True, sort all utterances by the
                number of frames and utteraces in each mini-batch are shuffled.
                Otherwise, shuffle utteraces.
            sort_stop_epoch (int, optional): After sort_stop_epoch, training
                will revert back to a random order
            progressbar (bool, optional): if True, visualize progressbar
        """
        if data_type not in ['train', 'dev', 'test']:
            raise TypeError('data_type must be "train" or "dev" or "test".')
        if label_type not in ['phone39', 'phone48', 'phone61', 'character',
                              'character_capital_divide']:
            raise TypeError(
                'label_type must be "phone39" or "phone48" or "phone61" or ' +
                '"character" or "character_capital_divide".')

        super(Dataset, self).__init__()

        self.data_type = data_type
        self.label_type = label_type
        self.batch_size = batch_size
        self.eos_index = eos_index
        self.max_epoch = max_epoch
        self.splice = splice
        self.num_stack = num_stack
        self.num_skip = num_skip
        self.shuffle = shuffle
        self.sort_utt = sort_utt
        self.sort_stop_epoch = sort_stop_epoch
        self.progressbar = progressbar
        self.ctc_padded_value = -1
        self.att_padded_value = eos_index

        input_path = join(
            '/n/sd8/inaguma/corpus/timit/dataset/inputs/htk/speaker',
            data_type)
        ctc_label_path = join(
            '/n/sd8/inaguma/corpus/timit/dataset/labels/ctc',
            label_type, data_type)
        att_label_path = join(
            '/n/sd8/inaguma/corpus/timit/dataset/labels/attention',
            label_type, data_type)

        # Load the frame number dictionary
        with open(join(input_path, 'frame_num.pickle'), 'rb') as f:
            self.frame_num_dict = pickle.load(f)

        # Sort paths to input & label
        axis = 1 if sort_utt else 0
        frame_num_tuple_sorted = sorted(self.frame_num_dict.items(),
                                        key=lambda x: x[axis])
        input_paths, att_label_paths, ctc_label_paths = [], [], []
        for input_name, frame_num in frame_num_tuple_sorted:
            input_paths.append(join(input_path, input_name + '.npy'))
            att_label_paths.append(join(att_label_path, input_name + '.npy'))
            ctc_label_paths.append(join(ctc_label_path, input_name + '.npy'))
        self.input_paths = np.array(input_paths)
        self.att_label_paths = np.array(att_label_paths)
        self.ctc_label_paths = np.array(ctc_label_paths)

        # Load all dataset in advance
        print('=> Loading dataset (%s, %s)...' % (data_type, label_type))
        input_list, att_label_list, ctc_label_list = [], [], []
        for i in wrap_iterator(range(len(self.input_paths)), self.progressbar):
            input_list.append(np.load(self.input_paths[i]))
            att_label_list.append(np.load(self.att_label_paths[i]))
            ctc_label_list.append(np.load(self.ctc_label_paths[i]))
        self.input_list = np.array(input_list)
        self.att_label_list = np.array(att_label_list)
        self.ctc_label_list = np.array(ctc_label_list)

        # Frame stacking
        print('=> Stacking frames...')
        self.input_list = stack_frame(self.input_list,
                                      self.input_paths,
                                      self.frame_num_dict,
                                      num_stack,
                                      num_skip,
                                      progressbar)

        self.rest = set(range(0, len(self.input_paths), 1))
