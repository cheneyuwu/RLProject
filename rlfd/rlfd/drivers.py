import abc
import pickle
from collections import deque

import numpy as np
import tensorflow as tf


class Driver(object, metaclass=abc.ABCMeta):

  def __init__(self, make_env, policy, render):
    """
    Driver that generates experience by interacting with one or many environments.

    Args:
        make_env (function) - a factory function that creates a new instance of the environment when called
        policy   (object)   - the policy that is used to act
        render   (bool)     - whether or not to render the rollouts
    """
    self.make_env = make_env
    self.policy = policy
    self.render = render

  @abc.abstractmethod
  def seed(self, seed):
    """set seed for internal environments"""

  @abc.abstractmethod
  def generate_rollouts(self, observers=()):
    """Generate experiences"""


class StepBasedDriver(Driver):

  def __init__(self,
               make_env,
               policy,
               num_steps=None,
               num_episodes=None,
               render=False):
    super().__init__(make_env=make_env, policy=policy, render=render)

    self.env = make_env()
    assert (any([num_steps == None, num_episodes == None]) and
            not all([num_steps == None, num_episodes == None]))
    self.num_steps = num_steps
    self.num_episodes = num_episodes
    self.eps_length = self.env.eps_length

    self.done = True
    self.curr_eps_step = 0

  def seed(self, seed):
    """Set seed for environment"""
    self.env.seed(seed)

  def generate_rollouts(self, observers=()):
    """generate `num_steps` rollouts"""

    # Special case for 0 step/episode.
    if not self.num_steps and not self.num_episodes:
      return None

    experiences = {k: [] for k in ("o", "o_2", "u", "r", "done")}

    current_step = 0
    current_episode = 0
    while ((self.num_steps != None and current_step < self.num_steps) or
           (self.num_episodes != None and current_episode < self.num_episodes)):
      # start a new episode if the last one is done
      if self.done or (self.curr_eps_step == self.eps_length):
        self.done = False
        self.curr_eps_step = 0
        self.o = self.env.reset()
      u = self.policy(self.o)
      # compute new states and observations
      o_2, r, self.done, info = self.env.step(u)
      if self.render:
        self.env.render()

      for observer in observers:
        observer(o=self.o,
                 o_2=o_2,
                 u=u,
                 r=r,
                 done=self.done,
                 info=info,
                 reset=self.done or (self.curr_eps_step + 1 == self.eps_length))

      experiences["o"].append(self.o)
      experiences["o_2"].append(o_2)
      experiences["u"].append(u)
      experiences["r"].append(r)
      experiences["done"].append(self.done)
      self.o = o_2

      current_step += 1
      self.curr_eps_step += 1
      if self.done or (self.curr_eps_step == self.eps_length):
        current_episode += 1

    # Store all information into an episode dict
    for key, value in experiences.items():
      experiences[key] = np.array(value).reshape(len(value), -1)

    return experiences


class EpisodeBasedDriver(StepBasedDriver):

  def __init__(self,
               make_env,
               policy,
               num_steps=None,
               num_episodes=None,
               render=False):
    assert num_episodes and (num_steps == None)
    super(EpisodeBasedDriver, self).__init__(make_env, policy, num_steps,
                                             num_episodes, render)

  def generate_rollouts(self, observers=()):
    experiences = super().generate_rollouts(observers=observers)
    assert all([
        v.shape[0] == self.num_episodes * self.eps_length
        for v in experiences.values()
    ])
    experiences = {
        k: v.reshape((self.num_episodes, self.eps_length, v.shape[-1]))
        for k, v in experiences.items()
    }
    return experiences
