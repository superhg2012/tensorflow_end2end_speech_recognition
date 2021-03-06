#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Base class of attention model."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
from models.attention.decoders.beam_search.util import choose_top_k
from models.attention.decoders.beam_search.beam_search_decoder import BeamSearchDecoder


OPTIMIZER_CLS_NAMES = {
    "adagrad": tf.train.AdagradOptimizer,
    "adadelta": tf.train.AdadeltaOptimizer,
    "adam": tf.train.AdamOptimizer,
    "momentum": tf.train.MomentumOptimizer,
    "rmsprop": tf.train.RMSPropOptimizer,
    "sgd": tf.train.GradientDescentOptimizer,
}

HELPERS = {
    "training": tf.contrib.seq2seq.TrainingHelper,
    "greedyembedding": tf.contrib.seq2seq.GreedyEmbeddingHelper
}


class AttentionBase(object):
    """Attention Mechanism based seq2seq model.
    Args:
        input_size: int, the dimension of input vectors
        attention_dim: int, the dimension of attention vecors
        num_classes: int, the number of nodes in output layer
        embedding_dim: int, the dimension of target embedding
        sos_index: index of the start of sentence tag (<SOS>)
        eos_index: index of the end of sentence tag (<EOS>)
        clip_grad: A float value. Range of gradient clipping (> 0)
        weight_decay: A float value. Regularization parameter for weight decay
        beam_width: if equal to 1, use greedy decoding
    """

    def __init__(self, *args, **kwargs):
        NotImplementedError

    def create_placeholders(self):
        """Create placeholders and append them to list."""
        self.inputs_pl_list.append(
            tf.placeholder(tf.float32, shape=[None, None, self.input_size],
                           name='input'))
        self.labels_pl_list.append(
            tf.placeholder(tf.int32, shape=[None, None], name='labels'))
        self.inputs_seq_len_pl_list.append(
            tf.placeholder(tf.int32, shape=[None], name='inputs_seq_len'))
        self.labels_seq_len_pl_list.append(
            tf.placeholder(tf.int32, shape=[None], name='labels_seq_len'))
        self.keep_prob_input_pl_list.append(
            tf.placeholder(tf.float32, name='keep_prob_input'))
        self.keep_prob_hidden_pl_list.append(
            tf.placeholder(tf.float32, name='keep_prob_hidden'))
        self.keep_prob_output_pl_list.append(
            tf.placeholder(tf.float32, name='keep_prob_output'))
        self.learning_rate_pl_list.append(
            tf.placeholder(tf.float32, name='learning_rate'))

        # These are prepared for computing LER
        self.labels_st_true_pl = tf.SparseTensor(
            tf.placeholder(tf.int64, name='indices_true'),
            tf.placeholder(tf.int32, name='values_true'),
            tf.placeholder(tf.int64, name='shape_true'))
        self.labels_st_pred_pl = tf.SparseTensor(
            tf.placeholder(tf.int64, name='indices_pred'),
            tf.placeholder(tf.int32, name='values_pred'),
            tf.placeholder(tf.int64, name='shape_pred'))

    def _add_noise_to_inputs(self, inputs, stddev=0.075):
        """Add gaussian noise to the inputs.
        Args:
            inputs: the noise free input-features.
            stddev: The standart deviation of the noise.
        Returns:
            inputs: Input features plus noise.
        """
        # if stddev != 0:
        #     with tf.variable_scope("input_noise"):
        #         # Add input noise with a standart deviation of stddev.
        #         inputs = tf.random_normal(
        #             tf.shape(inputs), 0.0, stddev) + inputs
        # return inputs
        raise NotImplementedError

    def _add_noise_to_gradients(grads_and_vars, gradient_noise_scale):
        """Adds scaled noise from a 0-mean normal distribution to gradients.
        Args:
            grads_and_vars:
            gradient_noise_scale:
            stddev:
        Returns:
        """
        raise NotImplementedError

    def _generate_target_embedding(self, reuse):
        """Returns the embedding used for the target sequence."""
        with tf.variable_scope("target_embedding", reuse=reuse):
            return tf.get_variable(
                name="W_embedding",
                shape=[self.num_classes, self.embedding_dim],
                initializer=tf.random_uniform_initializer(
                    -self.parameter_init,
                    self.parameter_init))
        # TODO: Consider shape of target_embedding

    def _beam_search_decoder_wrapper(self, decoder, beam_width=None,
                                     length_penalty_weight=0.6):
        """Wraps a decoder into a Beam Search decoder.
        Args:
            decoder: An instance of `RNNDecoder` class
            beam_width: int, the number of beams to use
            length_penalty_weight: A float value, weight for the length penalty
                factor. 0.0 disables the penalty.
        Returns:
            A callable BeamSearchDecoder with the same interfaces as the
                attention decoder
        """
        if beam_width is None or beam_width <= 1:
            # Greedy decoding
            self.use_beam_search = False
            return decoder

        self.use_beam_search = True
        return BeamSearchDecoder(
            decoder=decoder,
            beam_width=beam_width,
            vocab_size=self.num_classes,
            eos_index=self.eos_index,
            length_penalty_weight=length_penalty_weight,
            choose_successors_fn=choose_top_k)

    def _decode_train(self, decoder, bridge, encoder_outputs, labels,
                      labels_seq_len):
        """Runs decoding in training mode.
        Args:
            decoder: An instance of the decoder class
            bridge:
            encoder_outputs:
            labels: Target labels of size `[B, T, num_classes]`
            labels_seq_len: The length of target labels
        Returns:
            decoder_outputs: A tuple of `(AttentionDecoderOutput, final_state)`
        """
        # Convert target labels to one-hot vectors of size
        # `[batch_size, max_time, num_classes]`
        # labels = tf.one_hot(labels,
        #                     depth=self.num_classes,
        #                     on_value=1.0,
        #                     off_value=0.0,
        #                     axis=-1)

        # Generate embedding of target labels
        target_embedding = self._generate_target_embedding(reuse=False)
        target_embedded = tf.nn.embedding_lookup(target_embedding,
                                                 labels)

        helper_train = tf.contrib.seq2seq.TrainingHelper(
            inputs=target_embedded[:, :-1, :],  # embedding of target labels
            # inputs=labels[:, :-1, :],
            sequence_length=labels_seq_len - 1,  # include <SOS>, exclude <EOS>
            time_major=False)  # self.time_major??
        # target_embedded: `[batch_size, time, embedding_dim]`

        decoder_initial_state = bridge(reuse=False)

        # Call decoder class
        (decoder_outputs, final_state) = decoder(
            initial_state=decoder_initial_state,
            helper=helper_train,
            mode=tf.contrib.learn.ModeKeys.TRAIN)
        # NOTE: They are time-major if self.time_major is True

        return (decoder_outputs, final_state)

    def _decode_infer(self, decoder, bridge, encoder_outputs):
        """Runs decoding in inference mode.
        Args:
            decoder: An instance of the decoder class
            bridge:
            encoder_outputs: A namedtuple of
                outputs
                final_state
                attention_values
                attention_values_length
        Returns:
            decoder_outputs: A tuple of `(AttentionDecoderOutput, final_state)`
        """
        batch_size = tf.shape(encoder_outputs.outputs)[0]

        if self.use_beam_search:
            batch_size = self.beam_width
        # TODO: make this batch version

        target_embedding = self._generate_target_embedding(reuse=True)

        helper_infer = tf.contrib.seq2seq.GreedyEmbeddingHelper(
            # embedding=self.decoder_outputs_train.logits,
            embedding=target_embedding,  # embedding of predicted labels
            start_tokens=tf.fill([batch_size], self.sos_index),
            # start_tokens=tf.tile([self.sos_index], [batch_size]),
            end_token=self.eos_index)
        # ex.)
        # Output tensor has shape [2, 3].
        # tf.fill([2, 3], 9) ==> [[9, 9, 9]
        #                         [9, 9, 9]]

        decoder_initial_state = bridge(reuse=True)

        # Call decoder class
        (decoder_outputs, final_state) = decoder(
            initial_state=decoder_initial_state,
            helper=helper_infer,
            mode=tf.contrib.learn.ModeKeys.INFER)
        # NOTE: They are time-major if self.time_major is True

        return (decoder_outputs, final_state)

    def compute_loss(self, inputs, labels, inputs_seq_len, labels_seq_len,
                     keep_prob_input, keep_prob_hidden, keep_prob_output,
                     scope=None):
        """Operation for computing cross entropy sequence loss.
        Args:
            inputs: A tensor of `[B, T, input_size]`
            labels: A tensor of `[B, T]`
            inputs_seq_len: A tensor of `[B]`
            labels_seq_len: A tensor of `[B]`
            keep_prob_input: A float value. A probability to keep nodes in
                the input-hidden layer
            keep_prob_hidden: A float value. A probability to keep nodes in
                the hidden-hidden layers
            keep_prob_output: A float value. A probability to keep nodes in
                the hidden-output layer
        Returns:
            loss: operation for computing total loss (cross entropy sequence
                loss + L2). This is a single scalar tensor to minimize.
            logits:
            decoder_outputs_train:
            decoder_outputs_infer:
        """
        # Build model graph
        logits, decoder_outputs_train, decoder_outputs_infer = self._build(
            inputs, labels, inputs_seq_len, labels_seq_len,
            keep_prob_input, keep_prob_hidden, keep_prob_output)

        # For prevent 0 * log(0) in crossentropy loss
        epsilon = tf.constant(value=1e-10)
        logits = logits + epsilon

        # Weight decay
        if self.weight_decay > 0:
            with tf.name_scope("weight_decay_loss"):
                weight_sum = 0
                for var in tf.trainable_variables():
                    if 'bias' not in var.name.lower():
                        weight_sum += tf.nn.l2_loss(var)
                tf.add_to_collection('losses', weight_sum * self.weight_decay)

        with tf.name_scope("sequence_loss"):
            max_time = tf.shape(labels[:, 1:])[1]
            loss_mask = tf.sequence_mask(tf.to_int32(labels_seq_len - 1),
                                         maxlen=max_time,
                                         dtype=tf.float32)
            sequence_losses = tf.contrib.seq2seq.sequence_loss(
                logits=logits,
                targets=labels[:, 1:],
                weights=loss_mask,
                average_across_timesteps=True,
                average_across_batch=True,
                softmax_loss_function=None)

            sequence_loss = tf.reduce_sum(sequence_losses,
                                          name='sequence_loss_mean')
            tf.add_to_collection('losses', sequence_loss)

        # Compute total loss
        total_loss = tf.add_n(tf.get_collection('losses'), name='total_loss')

        # Add a scalar summary for the snapshot of loss
        if self.weight_decay > 0:
            self.summaries_train.append(
                tf.summary.scalar('weight_loss_train',
                                  weight_sum * self.weight_decay))
            self.summaries_dev.append(
                tf.summary.scalar('weight_loss_dev',
                                  weight_sum * self.weight_decay))
            self.summaries_train.append(
                tf.summary.scalar('total_loss_train', total_loss))
            self.summaries_dev.append(
                tf.summary.scalar('total_loss_dev', total_loss))

        self.summaries_train.append(
            tf.summary.scalar('sequence_loss_train', sequence_loss))
        self.summaries_dev.append(
            tf.summary.scalar('sequence_loss_dev', sequence_loss))

        return total_loss, logits, decoder_outputs_train, decoder_outputs_infer

    def set_optimizer(self, optimizer_name, learning_rate):
        """Set optimizer.
        Args:
            optimizer: string, name of the optimizer in OPTIMIZER_CLS_NAMES
            learning_rate: A float value, a learning rate
        Returns:
            optimizer:
        """
        optimizer_name = optimizer_name.lower()
        if optimizer_name not in OPTIMIZER_CLS_NAMES:
            raise ValueError(
                "Optimizer name should be one of [%s], you provided %s." %
                (", ".join(OPTIMIZER_CLS_NAMES), optimizer_name))

        # Select optimizer
        if optimizer_name == 'momentum':
            return OPTIMIZER_CLS_NAMES[optimizer_name](
                learning_rate=learning_rate,
                momentum=0.9)
        else:
            return OPTIMIZER_CLS_NAMES[optimizer_name](
                learning_rate=learning_rate)

    def train(self, loss, optimizer, learning_rate=None, clip_norm=False):
        """Operation for training. Only the sigle GPU training is supported.
        Args:
            loss: An operation for computing loss
            optimizer: string, name of the optimizer in OPTIMIZER_CLS_NAMES
            learning_rate: A float value, a learning rate
            clip_norm: if True, clip gradients norm by self.clip_grad
        Returns:
            train_op: operation for training
        """
        # Create a variable to track the global step
        global_step = tf.Variable(0, name='global_step', trainable=False)

        # Set optimizer
        self.optimizer = self.set_optimizer(optimizer, learning_rate)

        # TODO: Optionally wrap with SyncReplicasOptimizer

        if self.clip_grad is not None:
            # Compute gradients
            grads_and_vars = self.optimizer.compute_gradients(loss)

            # Clip gradients
            clipped_grads_and_vars = self._clip_gradients(grads_and_vars,
                                                          clip_norm)

            # Create gradient updates
            train_op = self.optimizer.apply_gradients(
                clipped_grads_and_vars,
                global_step=global_step)

        else:
            # Use the optimizer to apply the gradients that minimize the loss
            # and also increment the global step counter as a single training
            # step
            train_op = self.optimizer.minimize(loss, global_step=global_step)

        return train_op

    def _clip_gradients(self, grads_and_vars, _clip_norm):
        """Clip gradients.
        Args:
            grads_and_vars: list of (grads, vars) tuples
            _clip_norm: if True, clip gradients norm by self.clip_grad
        Returns:
            clipped_grads_and_vars: list of (clipped grads, vars)
        """
        # TODO: Optionally add gradient noise

        clipped_grads_and_vars = []

        if _clip_norm:
            # Clip gradient norm
            for grad, var in grads_and_vars:
                if grad is not None:
                    clipped_grads_and_vars.append(
                        (tf.clip_by_norm(grad, clip_norm=self.clip_grad), var))
        else:
            # Clip gradient
            for grad, var in grads_and_vars:
                if grad is not None:
                    clipped_grads_and_vars.append(
                        (tf.clip_by_value(grad,
                                          clip_value_min=-self.clip_grad,
                                          clip_value_max=self.clip_grad), var))

        # TODO: Add histograms for variables, gradients (norms)
        # self._tensorboard(trainable_vars)

        return clipped_grads_and_vars

    def decoder(self, decoder_outputs_train, decoder_outputs_infer):
        """Operation for decoding.
        Args:
            decoder_outputs_train: An instance of ``
            decoder_outputs_infer: An instance of ``
        Return:
            decoded_train: operation for decoding in training. A tensor of
                size `[B, ]`
            decoded_infer: operation for decoding in inference. A tensor of
                size `[, max_decode_length]`
        """
        decoded_train = decoder_outputs_train.predicted_ids

        if self.use_beam_search:
            # Beam search decoding
            decoded_infer = decoder_outputs_infer.predicted_ids[0]

            # predicted_ids = decoder_outputs_infer.beam_search_output.predicted_ids
            # scores = decoder_outputs_infer.beam_search_output.scores[:, :, -1]
            # argmax_score = tf.argmax(scores, axis=0)[0]
            # NOTE: predicted_ids: `[time, 1, beam_width]`

            # Convert to `[beam_width, 1, time]`
            # predicted_ids = tf.transpose(predicted_ids, (2, 1, 0))

            # decoded_infer = predicted_ids[argmax_score]
            # decoded_infer = decoder_outputs_infer.predicted_ids[-1]
        else:
            # Greedy decoding
            decoded_infer = decoder_outputs_infer.predicted_ids

            argmax_score = None

        return decoded_train, decoded_infer

    def compute_ler(self, labels_true, labels_pred):
        """Operation for computing LER (Label Error Rate).
        Args:
            labels_true: A SparseTensor
            labels_pred: A SparseTensor
        Returns:
            ler_op: operation for computing LER
        """
        # Compute LER (normalize by label length)
        ler_op = tf.reduce_mean(tf.edit_distance(
            labels_pred, labels_true, normalize=True))
        # TODO: パディングを考慮して計算する

        # Add a scalar summary for the snapshot of LER
        # with tf.name_scope("ler"):
        #     self.summaries_train.append(tf.summary.scalar(
        #         'ler_train', ler_op))
        #     self.summaries_dev.append(tf.summary.scalar(
        #         'ler_dev', ler_op))
        # TODO: feed_dictのタイミング違うからエラーになる

        return ler_op
