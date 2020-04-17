# coding=utf-8
# Copyright 2018 The TF-Agents Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""End-to-end test for bandit training under stationary linear environments."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import copy
import functools
import os
from absl import app
from absl import flags
import numpy as np
import tensorflow as tf  # pylint: disable=g-explicit-tensorflow-version-import


from tf_agents.bandits.agents import neural_epsilon_greedy_agent
from tf_agents.bandits.agents.examples.v2 import trainer
from tf_agents.bandits.environments import stationary_stochastic_per_arm_py_environment as sspe
from tf_agents.bandits.metrics import tf_metrics as tf_bandit_metrics
from tf_agents.bandits.networks import global_and_arm_feature_network
from tf_agents.bandits.policies import policy_utilities
from tf_agents.bandits.specs import utils as bandit_spec_utils
from tf_agents.environments import tf_py_environment

flags.DEFINE_string('root_dir', os.getenv('TEST_UNDECLARED_OUTPUTS_DIR'),
                    'Root directory for writing logs/summaries/checkpoints.')

flags.DEFINE_enum(
    'network', 'commontower', ['commontower', 'dotproduct'],
    'Which network architecture to use. '
    'Possible values are `commontower` and `dotproduct`.')

flags.DEFINE_bool('drop_arm_obs', False, 'Whether to wipe the arm observations '
                  'from the trajectories.')

FLAGS = flags.FLAGS

BATCH_SIZE = 16
NUM_ACTIONS = 7
HIDDEN_PARAM = [0, 1, 2, 3, 4, 5, 6, 7, 8]
TRAINING_LOOPS = 2000
STEPS_PER_LOOP = 2

EPSILON = 0.01
LR = 0.05


def _all_rewards(observation, hidden_param):
  """Helper function that outputs rewards for all actions, given an observation."""
  hidden_param = tf.cast(hidden_param, dtype=tf.float32)
  global_obs = observation[bandit_spec_utils.GLOBAL_FEATURE_KEY]
  per_arm_obs = observation[bandit_spec_utils.PER_ARM_FEATURE_KEY]
  num_actions = tf.shape(per_arm_obs)[1]
  tiled_global = tf.tile(
      tf.expand_dims(global_obs, axis=1), [1, num_actions, 1])
  concatenated = tf.concat([tiled_global, per_arm_obs], axis=-1)
  rewards = tf.linalg.matvec(concatenated, hidden_param)
  return rewards


def optimal_reward(observation, hidden_param):
  return tf.reduce_max(_all_rewards(observation, hidden_param), axis=1)


def optimal_action(observation, hidden_param):
  return tf.argmax(
      _all_rewards(observation, hidden_param), axis=1, output_type=tf.int32)


def main(unused_argv):
  tf.compat.v1.enable_v2_behavior()  # The trainer only runs with V2 enabled.

  class LinearNormalReward(object):

    def __init__(self, theta):
      self.theta = theta

    def __call__(self, x):
      mu = np.dot(x, self.theta)
      return np.random.normal(mu, 1)

  def _global_context_sampling_fn():
    return np.random.randint(-10, 10, [4]).astype(np.float32)

  def _arm_context_sampling_fn():
    return np.random.randint(-2, 3, [5]).astype(np.float32)

  reward_fn = LinearNormalReward(HIDDEN_PARAM)

  env = sspe.StationaryStochasticPerArmPyEnvironment(
      _global_context_sampling_fn,
      _arm_context_sampling_fn,
      NUM_ACTIONS,
      reward_fn,
      batch_size=BATCH_SIZE)
  environment = tf_py_environment.TFPyEnvironment(env)

  obs_spec = environment.observation_spec()
  if FLAGS.network == 'commontower':
    network = (
        global_and_arm_feature_network.create_feed_forward_common_tower_network(
            obs_spec, (4, 3), (3, 4), (4, 2)))
  elif FLAGS.network == 'dotproduct':
    network = (
        global_and_arm_feature_network.create_feed_forward_dot_product_network(
            obs_spec, (4, 3, 6), (3, 4, 6)))
  if FLAGS.drop_arm_obs:
    def drop_arm_feature_fn(traj):
      transformed_traj = copy.deepcopy(traj)
      del transformed_traj.observation[bandit_spec_utils.PER_ARM_FEATURE_KEY]
      return transformed_traj
  else:
    drop_arm_feature_fn = None
  agent = neural_epsilon_greedy_agent.NeuralEpsilonGreedyAgent(
      time_step_spec=environment.time_step_spec(),
      action_spec=environment.action_spec(),
      reward_network=network,
      optimizer=tf.compat.v1.train.AdamOptimizer(learning_rate=LR),
      epsilon=EPSILON,
      accepts_per_arm_features=True,
      training_data_spec_transformation_fn=drop_arm_feature_fn,
      emit_policy_info=policy_utilities.InfoFields.PREDICTED_REWARDS_MEAN)

  optimal_reward_fn = functools.partial(
      optimal_reward, hidden_param=HIDDEN_PARAM)
  optimal_action_fn = functools.partial(
      optimal_action, hidden_param=HIDDEN_PARAM)
  regret_metric = tf_bandit_metrics.RegretMetric(optimal_reward_fn)
  suboptimal_arms_metric = tf_bandit_metrics.SuboptimalArmsMetric(
      optimal_action_fn)

  trainer.train(
      root_dir=FLAGS.root_dir,
      agent=agent,
      environment=environment,
      training_loops=TRAINING_LOOPS,
      steps_per_loop=STEPS_PER_LOOP,
      additional_metrics=[regret_metric, suboptimal_arms_metric],
      training_data_spec_transformation_fn=drop_arm_feature_fn)


if __name__ == '__main__':
  app.run(main)
