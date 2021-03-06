from datetime import datetime
from statistics import mean

import numpy as np
import plac

from learning2write import get_pattern_set, VALID_PATTERN_SETS
from learning2write.env import WritingEnvironment
from train import get_model_type


@plac.annotations(
    model_path=plac.Annotation('The path and the filename of the saved model to run.',
                               type=str, kind='positional'),
    model_type=plac.Annotation('The type of model that is being loaded.', choices=['acktr', 'acer', 'ppo'],
                               type=str, kind='positional'),
    pattern_set=plac.Annotation('The set of patterns to use in the environment.', choices=VALID_PATTERN_SETS,
                                kind='option', type=str),
    rotate_patterns=plac.Annotation('Flag indicating that patterns should be randomly rotated.', kind='flag'),
    max_updates=plac.Annotation('The maximum number of steps to perform in the evironment.', type=int, kind='option'),
    max_steps=plac.Annotation('The maximum number of steps to perform per episode.', type=int, kind='option'),
    fps=plac.Annotation('How many steps to perform per second.', type=float, kind='option')
)
def main(model_path, model_type, pattern_set='3x3', rotate_patterns=False, max_updates=1000, max_steps=100, fps=10.0):
    """Run a model in the writing environment in test mode (i.e. no training, just predictions).

    Press `Q` or `ESCAPE` to quit at any time.
    """

    pattern_set = get_pattern_set(pattern_set, rotate_patterns)
    model = get_model_type(model_type).load(model_path)

    with WritingEnvironment(pattern_set) as env:
        episode = 0
        updates = 0
        rewards = []
        n_correct = 0

        while updates < max_updates:
            episode += 1
            steps, reward, mean_reward, is_correct = run_episode(env, episode, fps, updates, max_updates, max_steps,
                                                                 model)
            rewards.append(reward)
            updates += steps
            n_correct += 1 if is_correct else 0

            print('\rEpisode %02d - Steps: %d - Mean Reward: %.2f - Return: %.2f - Return Moving Avg.: %.2f - '
                  'Accuracy: %.2f'
                  % (episode, steps, mean_reward, reward, mean(rewards[-1 - min(len(rewards) - 1, 100):]),
                     n_correct / episode) + ' ' * 40)

            if env.should_quit:
                break


def run_episode(env, episode, fps, updates, max_updates, max_steps, model):
    observation = env.reset()
    step = 0
    rewards = []

    for step in range(max_steps):
        start = datetime.now()
        action, _ = model.predict(observation)
        observation, reward, done, _ = env.step(action)
        rewards.append(reward)

        print('\rEpisode %02d - Step %02d - Reward: %.2f - Mean Reward: %.2f - Return: %.2f'
              % (episode, step + 1, reward, mean(rewards), sum(rewards)), end='')
        env.render()
        env.wait(1.0 / fps - (datetime.now() - start).total_seconds())  # sync steps to framerate (`fps`)
        updates += 1

        if done or env.should_quit or updates >= max_updates:
            break

    return step + 1, sum(rewards), mean(rewards), np.array_equal(env.pattern, env.reference_pattern)


if __name__ == '__main__':
    plac.call(main)
