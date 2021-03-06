import os
from datetime import datetime
from typing import Optional, Type, Tuple

import numpy as np
import plac
import tensorflow as tf
from stable_baselines import ACKTR, PPO2, ACER
from stable_baselines.a2c.utils import conv, conv_to_fc, linear
from stable_baselines.common import ActorCriticRLModel
from stable_baselines.common.policies import FeedForwardPolicy, MlpPolicy, CnnPolicy
from stable_baselines.common.vec_env import SubprocVecEnv

from learning2write import WritingEnvironment, get_pattern_set, EMNIST_PATTERN_SETS, VALID_PATTERN_SETS
from learning2write.patterns import PatternSet


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

    def save_model(self, model: ActorCriticRLModel, checkpoint_name=None):
        """Save a checkpoint.

        :param model: The model to save.
        :param checkpoint_name: The name to save the checkpoint under. If None a name is automatically generated based
                                on the number of updates.
        """
        checkpoint = os.path.join(self.checkpoint_path,
                                  checkpoint_name if checkpoint_name else 'checkpoint_%05d' % self._updates)
        print('[%s] Saving checkpoint \'%s.pkl\'...' % (datetime.now(), checkpoint))
        model.save(checkpoint)


class MlpPolicy5x5(FeedForwardPolicy):
    def __init__(self, sess, ob_space, ac_space, n_env, n_steps, n_batch, **kwargs):
        super().__init__(sess, ob_space, ac_space, n_env, n_steps, n_batch,
                         net_arch=[64, {'vf': [64, 64], 'pi': [64, 64]}],
                         feature_extraction='mlp',
                         **kwargs)


class MlpPolicyEmnist(FeedForwardPolicy):
    def __init__(self, sess, ob_space, ac_space, n_env, n_steps, n_batch, **kwargs):
        super().__init__(sess, ob_space, ac_space, n_env, n_steps, n_batch,
                         net_arch=[256, 64, {'vf': [16], 'pi': [16]}],
                         feature_extraction='mlp',
                         **kwargs)


def get_env(n_workers: int, pattern_set: PatternSet) -> SubprocVecEnv:
    """Create a vectorised writing environment.

    :param n_workers: The number of instances of the environment to run in parallel.
    :param pattern_set: The pattern set to be used in the environment.
    :return: The environment instance.
    """
    # Give the agent at most just enough moves to cover the grid world exactly.
    max_steps = 2 * pattern_set.width * pattern_set.height

    return SubprocVecEnv([lambda: WritingEnvironment(pattern_set, max_steps=max_steps) for _ in range(n_workers)])


def get_model(env: SubprocVecEnv, model_path: Optional[str], model_type: str, pattern_set: PatternSet,
              policy_type: str, er_buffer_size=1000000,
              tensorboard_log_path: Optional[str] = None) -> ActorCriticRLModel:
    """Create the RL agent model, optionally loaded from a previously trained model.

    :param env: The vectorised gym environment (see stable_baselines.common.vec_env.SubprocVecEnv) to use with
                the model.
    :param model_path: The path to a saved model. If None a new model is created.
    :param model_type: The name of the type of model to use.
    :param pattern_set: The pattern set that the model will be trained on.
    :param policy_type: The name of the type of policy to use for the model.
    :param er_buffer_size: The size of the experience replay buffer to use with ACER models.
    :param tensorboard_log_path: The path to log training for use with Tensorboard.
    :return: The instance of the RL agent.
    """
    if model_path:
        model = get_model_type(model_type).load(model_path, tensorboard_log=tensorboard_log_path,
                                                _init_setup_model=False)
        model.set_env(env)

        if isinstance(model, ACER):
            model.buffer_size = er_buffer_size

        model.setup_model()
    else:
        policy, policy_kwargs = get_policy(policy_type, pattern_set)
        model = get_model_type(model_type)(policy, env, verbose=1, tensorboard_log=tensorboard_log_path,
                                           policy_kwargs=policy_kwargs)
    return model


def get_policy(policy_type: str, pattern_set: PatternSet) -> Tuple[Type[FeedForwardPolicy], dict]:
    """Translate a policy type from a string to a class type.

    :param policy_type: The name of the type of policy.
    :param pattern_set: The pattern set that the model will be trained on.
    :return: The class corresponding to the name and the relevant kwargs dictionary.
             Raises ValueError if the name is not recognised.
    """
    policy_kwargs = dict()

    if policy_type == 'mlp':
        policy = MlpPolicy
    elif policy_type == 'mlp5x5':
        policy = MlpPolicy5x5
    elif policy_type == 'mlpemnist':
        assert pattern_set.name in EMNIST_PATTERN_SETS, 'MlpPolicyEmnist policy must be used with an EMNIST pattern set.'
        policy = MlpPolicyEmnist
    elif policy_type == 'cnn':
        assert pattern_set.name != '3x3', 'A CNN policy can only be used with the following pattern sets: %s.' \
                                          % (['3x3'] + list(EMNIST_PATTERN_SETS))

        if pattern_set.name in EMNIST_PATTERN_SETS:
            cnn_feature_extractor = emnist_cnn_feature_extractor
        else:
            cnn_feature_extractor = small_cnn_feature_extractor

        policy = CnnPolicy
        policy_kwargs = {'cnn_extractor': cnn_feature_extractor}
    else:
        raise 'Unrecognised policy type \'%s\'' % policy_type
    return policy, policy_kwargs


def get_model_type(model_type) -> Type[ActorCriticRLModel]:
    """Translate a model name from a string to a class type.

    :param model_type: The name of the type of model.
    :return: The class corresponding to the name.
             Raises ValueError if the name is not recognised.
    """
    if model_type == 'acktr':
        return ACKTR
    elif model_type == 'ppo':
        return PPO2
    elif model_type == 'acer':
        return ACER
    else:
        raise ValueError('Unrecognised model type \'%s\'' % model_type)


def small_cnn_feature_extractor(scaled_images, **kwargs):
    """
    CNN feature extractor for 5x5 images.

    :param scaled_images: (TensorFlow Tensor) Image input placeholder
    :param kwargs: (dict) Extra keywords parameters for the convolutional layers of the CNN
    :return: (TensorFlow Tensor) The CNN output layer
    """
    activ = tf.nn.selu
    layer_1 = activ(conv(scaled_images, 'c1', n_filters=16, filter_size=3, stride=1, init_scale=np.sqrt(2), **kwargs))
    layer_2 = activ(conv(layer_1, 'c2', n_filters=32, filter_size=3, stride=1, init_scale=np.sqrt(2), **kwargs))
    layer_3 = conv_to_fc(layer_2)

    return activ(linear(layer_3, 'fc1', n_hidden=64, init_scale=np.sqrt(2)))


def emnist_cnn_feature_extractor(scaled_images, **kwargs):
    """
    CNN feature extractor for EMNIST images (28x28).

    :param scaled_images: (TensorFlow Tensor) Image input placeholder
    :param kwargs: (dict) Extra keywords parameters for the convolutional layers of the CNN
    :return: (TensorFlow Tensor) The CNN output layer
    """
    activ = tf.nn.selu
    layer_1 = activ(conv(scaled_images, 'c1', n_filters=32, filter_size=7, stride=4, init_scale=np.sqrt(2), **kwargs))
    layer_2 = activ(conv(layer_1, 'c2', n_filters=64, filter_size=5, stride=1, init_scale=np.sqrt(2), **kwargs))
    layer_3 = conv_to_fc(layer_2)

    return activ(linear(layer_3, 'fc1', n_hidden=128, init_scale=np.sqrt(2)))


def get_checkpointer(checkpoint_frequency: int, checkpoint_path: Optional[str], model: ActorCriticRLModel,
                     policy_type: str, pattern_set: str) -> Optional[CheckpointHandler]:
    """Create a CheckpointHandler based on certain parameters.

    :param checkpoint_frequency: How often to save checkpoints. Checkpoints are disabled if this is less than one.
    :param checkpoint_path: Where to save the checkpoints. If `None` then a path is automatically generated.
    :param model: The model to save training progress for.
    :param policy_type: The name of the type of policy to use for the model.
    :param pattern_set: The name of the set of patterns that the model will be trained on.
    :return: A CheckpointHandler if `checkpoint_checkpoint_frequency` > 0, None otherwise.
    """
    if checkpoint_frequency > 0:
        timestamp = ''.join(map(lambda s: '%02d' % s, datetime.now().utctimetuple()))
        path = checkpoint_path if checkpoint_path else 'checkpoints/%s_%s_%s_%s/' % (model.__class__.__name__.lower(),
                                                                                     policy_type,
                                                                                     pattern_set,
                                                                                     timestamp)
        checkpointer = CheckpointHandler(checkpoint_frequency, path)
    else:
        checkpointer = None
    return checkpointer


@plac.annotations(
    pattern_set=plac.Annotation('The set of patterns to use in the environment.',
                                choices=VALID_PATTERN_SETS,
                                kind='option', type=str),
    rotate_patterns=plac.Annotation('Flag indicating that patterns should be randomly rotated.', kind='flag'),
    emnist_batch_size=plac.Annotation('If using an EMNIST-based pattern set, how many images that should be loaded and '
                                      'kept in memory at once.',
                                      kind='option', type=int),
    model_type=plac.Annotation('The type of model to use. This is ignored if loading a model.',
                               choices=['acktr', 'acer', 'ppo'],
                               type=str, kind='option'),
    model_path=plac.Annotation('Continue training a model specified by a path to a saved model.',
                               type=str, kind='option'),
    er_buffer_size=plac.Annotation('The size of the experience replay buffer to use. '
                                   'Ignored for all models but ACER.',
                                   type=int, kind='option'),
    policy_type=plac.Annotation('The type of policy network to use. This is ignored if loading a model.',
                                choices=['mlp', 'mlp5x5', 'mlpemnist', 'cnn'],
                                type=str, kind='option'),
    steps=plac.Annotation('How steps to train the model for.',
                          type=int, kind='option'),
    n_workers=plac.Annotation('How many workers to train with.',
                              type=int, kind='option'),
    checkpoint_path=plac.Annotation('The directory to save checkpoint data to. '
                                    'Defaults to \'checkpoints/<pattern-set>/\'',
                                    type=str, kind='option'),
    checkpoint_frequency=plac.Annotation('How often (in number of updates, not timesteps) to save the model during '
                                         'training. Set to zero to disable checkpointing.',
                                         type=int, kind='option'),

)
def main(pattern_set='3x3', rotate_patterns=False, emnist_batch_size=512, model_type='acktr', model_path=None,
         er_buffer_size=1000000, policy_type='mlp',
         steps=1000000, n_workers=4, checkpoint_path=None, checkpoint_frequency=10000):
    """Train an A2C-based RL agent on the learning2write environment."""
    pattern_set_ = get_pattern_set(pattern_set, rotate_patterns, emnist_batch_size)

    env = get_env(n_workers, pattern_set_)
    model = get_model(env, model_path, model_type, pattern_set_, policy_type, er_buffer_size,
                      tensorboard_log_path='./tensorboard/')
    checkpointer = get_checkpointer(checkpoint_frequency, checkpoint_path, model, policy_type, pattern_set)

    try:
        model.learn(total_timesteps=steps, tb_log_name='%s_%s_%s' % (pattern_set.upper(),
                                                                     model.__class__.__name__.upper(),
                                                                     model.policy.__name__.upper()),
                    reset_num_timesteps=model_path is None, callback=checkpointer)
        checkpointer.save_model(model, 'checkpoint_last')
    except KeyboardInterrupt:
        # TODO: Make this work properly... Currently a SIGINT causes the workers for ACKTR to
        #  raise BrokenPipeError or EOFError.
        print('Stopping training...')
    finally:
        env.close()


if __name__ == '__main__':
    plac.call(main)
