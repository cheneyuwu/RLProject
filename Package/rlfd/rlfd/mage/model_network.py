import tensorflow as tf
import tensorflow_probability as tfp

tfd = tfp.distributions


class ModelNetwork(tf.keras.Model):

  def __init__(self, dimo, dimu, max_u, layer_sizes):

    super().__init__()

    self.dimo = dimo
    self.dimu = dimu
    self.max_u = max_u

    # build layers
    self._mlp_layers = []
    for size in layer_sizes:
      layer = tf.keras.layers.Dense(
          units=size,
          activation="swish",
          kernel_initializer=tf.keras.initializers.GlorotNormal(),
          bias_initializer=None,
      )
      self._mlp_layers.append(layer)

    output_dim = self.dimo[0] + 1  # 1 for reward
    self._mlp_layers.append(
        tf.keras.layers.Dense(
            units=output_dim * 2,
            kernel_initializer=tf.keras.initializers.GlorotNormal(),
            bias_initializer=None,
        ))

    # max and min log variance
    self._max_logvar = tf.Variable(
        tf.ones([1, output_dim]) / 2.,
        dtype=tf.float32,
        trainable=True,
    )
    self._min_logvar = tf.Variable(
        -tf.ones([1, output_dim]) * 10.,
        dtype=tf.float32,
        trainable=True,
    )

    self.output_dim = output_dim

  @property
  def max_logvar(self):
    return self._max_logvar

  @property
  def min_logvar(self):
    return self._min_logvar

  @tf.function
  def call(self, inputs):
    o, u = inputs
    output = tf.concat([o, u / self.max_u], axis=1)
    for l in self._mlp_layers:
      output = l(output)

    # TODO: maybe add activation to the output mean here? (original impl.)
    mean = output[..., :output.shape[-1] // 2]
    # TODO: check whether this is correct
    logvar = output[..., output.shape[-1] // 2:]
    logvar = self._max_logvar - tf.math.softplus(self._max_logvar - logvar)
    logvar = self._min_logvar + tf.math.softplus(logvar - self._min_logvar)
    var = tf.exp(logvar)

    obs_mean = mean[..., :self.dimo[0]]
    obs_var = var[..., :self.dimo[0]]
    rew_mean = mean[..., self.dimo[0]:]
    rew_var = var[..., self.dimo[0]:]

    return (obs_mean, rew_mean), (obs_var, rew_var)


class EnsembleModelNetwork(tf.keras.Model):

  def __init__(self, dimo, dimu, max_u, layer_sizes, num_networks, num_elites):

    super().__init__()

    self.dimo = dimo
    self.dimu = dimu
    self.max_u = max_u

    self._num_networks = num_networks
    self._num_elites = num_elites

    self._elites_inds = tf.Variable(tf.range(1, num_elites + 1),
                                    trainable=False)

    self._model_networks = [
        ModelNetwork(dimo, dimu, max_u, layer_sizes)
        for _ in range(num_networks)
    ]

    self._min_logvar = tf.concat([mn.min_logvar for mn in self._model_networks],
                                 axis=0)
    self._max_logvar = tf.concat([mn.max_logvar for mn in self._model_networks],
                                 axis=0)

  @property
  def max_logvar(self):
    return self._max_logvar

  @property
  def min_logvar(self):
    return self._min_logvar

  # @tf.function
  def call(self, inputs):
    o, u = inputs

    if len(o.shape) == 3:
      assert o.shape[0] == self._num_networks
      output = [
          self._model_networks[i]((o[i], u[i]))
          for i in range(self._num_networks)
      ]
    else:
      output = [
          self._model_networks[i]((o, u)) for i in range(self._num_networks)
      ]

    mean, var = list(zip(*output))
    obs_mean, rew_mean = list(zip(*mean))
    obs_var, rew_var = list(zip(*var))

    obs_mean, rew_mean = tf.stack(obs_mean), tf.stack(rew_mean)
    obs_var, rew_var = tf.stack(obs_var), tf.stack(rew_var)

    return (obs_mean, rew_mean), (obs_var, rew_var)

  @property
  def num_networks(self):
    return self._num_networks

  @property
  def num_elites(self):
    return self._num_elites

  def set_elite_inds(self, elites_inds):
    self._elites_inds.assign(elites_inds)

  def get_elite_inds(self):
    return self._elites_inds


if __name__ == "__main__":
  pass
