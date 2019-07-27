import os
from datetime import datetime

import numpy as np
import plac as plac
import tensorflow as tf
from stable_baselines import ACKTR
from stable_baselines.a2c.utils import conv, conv_to_fc, linear
from stable_baselines.common import BaseRLModel
from stable_baselines.common.policies import MlpPolicy, CnnPolicy
from stable_baselines.common.vec_env import SubprocVecEnv

from learning2write import WritingEnvironment, get_pattern_set, EMNIST_PATTERN_SETS, VALID_PATTERN_SETS


class CheckpointHandler:
    """Callback that handles saving training progress."""

    def __init__(self, interval, checkpoint_path='checkpoints'):
        """Create a new checkpoint callback.

        :param interval: How often (in updates) to save the model during training.
        :param checkpoint_path: Where to save the checkpoint data. This directory is created if it does not exist.
        """
        self._updates = 0
        self.interval = interval
        self.checkpoint_path = checkpoint_path

        os.makedirs(self.checkpoint_path, exist_ok=True)

    def __call__(self, locals_: dict, globals_: dict, *args, **kwargs):
        """Save a checkpoint if the time is right ;)

        :param locals_: A dict of local variables. This should be the local variables of the model's learn function.
        :param globals_: A dict of global variables that are available to the model.
        :return: True to indicate training should continue.
        """
        if self._updates % self.interval == 0:
            self.save_model(locals_['self'])

        self._updates += 1

        return True

    def save_model(self, model: BaseRLModel, checkpoint_name=None):
        """Save a checkpoint.

        :param model: The model to save.
        :param checkpoint_name: The name to save the checkpoint under. If None a name is automatically generated based
                                on the number of updates.
        """
        checkpoint = os.path.join(self.checkpoint_path,
                                  checkpoint_name if checkpoint_name else 'checkpoint_%05d' % self._updates)
        print('[%s] Saving checkpoint to \'%s\'...' % (datetime.now(), checkpoint))
        model.save(checkpoint)


def emnist_cnn_feature_extractor(scaled_images, **kwargs):
    """
    CNN from Nature paper.

    :param scaled_images: (TensorFlow Tensor) Image input placeholder
    :param kwargs: (dict) Extra keywords parameters for the convolutional layers of the CNN
    :return: (TensorFlow Tensor) The CNN output layer
    """
    activ = tf.nn.relu
    layer_1 = activ(conv(scaled_images, 'c1', n_filters=16, filter_size=4, stride=2, init_scale=np.sqrt(2), **kwargs))
    layer_2 = activ(conv(layer_1, 'c2', n_filters=32, filter_size=3, stride=1, init_scale=np.sqrt(2), **kwargs))
    layer_3 = conv_to_fc(layer_2)
    return activ(linear(layer_3, 'fc1', n_hidden=256, init_scale=np.sqrt(2)))


@plac.annotations(
    model_path=plac.Annotation('Continue training a model specified by a path to a saved model.',
                               type=str, kind='option'),
    policy_type=plac.Annotation('The type of policy network to use.Ignored if loading a model.',
                                type=str, kind='option', choices=['mlp', 'cnn']),
    pattern_set=plac.Annotation('The set of patterns to use in the environment.', choices=VALID_PATTERN_SETS,
                                kind='option', type=str),
    updates=plac.Annotation('How steps to train the model for.', type=int, kind='option'),
    checkpoint_path=plac.Annotation('The directory to save checkpoint data to. '
                                    'Defaults to \'checkpoints/<pattern-set>/\'', type=str, kind='option'),
    checkpoint_frequency=plac.Annotation('How often (in number of updates, not timesteps) to save the model during '
                                         'training. Set to zero to disable checkpointing.', type=int, kind='option'),
    n_workers=plac.Annotation('How many workers, or cpus, to train with.', type=int, kind='option')
)
def main(model_path=None, policy_type='mlp', pattern_set='3x3', updates=100000,
         checkpoint_path=None, checkpoint_frequency=1000,
         n_workers=4):
    """Train an ACKTR RL agent on the learning2write environment."""

    env = SubprocVecEnv([lambda: WritingEnvironment(get_pattern_set(pattern_set)) for _ in range(n_workers)])
    tensorboard_log = "./tensorboard/"

    # TODO: Make type of model configurable via cli
    if model_path:
        model = ACKTR.load(model_path, tensorboard_log=tensorboard_log)
        model.set_env(env)
    else:
        if policy_type == 'mlp':
            policy = MlpPolicy
        elif policy_type == 'cnn':
            assert pattern_set in EMNIST_PATTERN_SETS, 'A CNN policy must be used with an EMNIST pattern set.'
            policy = CnnPolicy
        else:
            raise 'Unrecognised policy type \'%s\'' % policy_type

        model = ACKTR(policy, env, verbose=1, tensorboard_log=tensorboard_log,
                      policy_kwargs={'cnn_extractor': emnist_cnn_feature_extractor})

    if checkpoint_frequency > 0:
        timestamp = ''.join(map(lambda s: '%02d' % s, datetime.now().utctimetuple()))
        path = checkpoint_path if checkpoint_path else 'checkpoints/%s_%s_%s/' % (model.__class__.__name__.lower(),
                                                                                  pattern_set,
                                                                                  timestamp)
        checkpointer = CheckpointHandler(checkpoint_frequency, path)
    else:
        checkpointer = None

    try:
        model.learn(total_timesteps=updates, tb_log_name='ACKTR_%s_%s' % (pattern_set.upper(),
                                                                          model.policy.__name__.upper()),
                    reset_num_timesteps=model_path is None, callback=checkpointer)
        checkpointer.save(model, "checkpoint_last" % pattern_set)
    except KeyboardInterrupt:
        # TODO: Make this work properly... Currently a SIGINT causes the workers for ACKTR to
        #  raise BrokenPipeError or EOFError.
        env.close()
        print('Stopping training...')


if __name__ == '__main__':
    plac.call(main)
