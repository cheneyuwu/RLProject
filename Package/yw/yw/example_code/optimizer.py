# =============================================================================
# Import
# =============================================================================

# Infra import
import tensorflow as tf
import numpy as np

try:
    from mpi4py import MPI
except ImportError:
    MPI = None

# DDPG Package import
import yw.util.tf_util as U


class Adam(object):
    def __init__(self, var_list, *, beta1=0.9, beta2=0.999, epsilon=1e-08, scale_grad_by_procs=True, comm=None):
        self.var_list = var_list
        self.beta1 = beta1
        self.beta2 = beta2
        self.epsilon = epsilon
        self.scale_grad_by_procs = scale_grad_by_procs
        size = sum(U.numel(v) for v in var_list)
        self.m = np.zeros(size, "float32")
        self.v = np.zeros(size, "float32")
        self.t = 0
        self.setfromflat = U.SetFromFlat(var_list)
        self.getflat = U.GetFlat(var_list)
        self.comm = MPI.COMM_WORLD if comm is None and MPI is not None else comm

    def update(self, localg, stepsize):
        localg = localg.astype("float32")
        globalg = np.copy(localg)
        self.t += 1
        a = stepsize * np.sqrt(1 - self.beta2 ** self.t) / (1 - self.beta1 ** self.t)
        self.m = self.beta1 * self.m + (1 - self.beta1) * globalg
        self.v = self.beta2 * self.v + (1 - self.beta2) * (globalg * globalg)
        step = (-a) * self.m / (np.sqrt(self.v) + self.epsilon)
        self.setfromflat(self.getflat() + step)

@U.in_session
def test_MpiAdam():
    np.random.seed(0)
    tf.set_random_seed(0)

    a = tf.Variable(np.random.randn(3).astype("float32"))
    b = tf.Variable(np.random.randn(2, 5).astype("float32"))
    loss = tf.reduce_sum(tf.square(a)) + tf.reduce_sum(tf.sin(b))

    stepsize = 1e-2
    update_op = tf.train.AdamOptimizer(stepsize).minimize(loss)
    do_update = U.function([], loss, updates=[update_op])

    tf.get_default_session().run(tf.global_variables_initializer())
    losslist_ref = []
    for i in range(10):
        l = do_update()
        print(i, l)
        losslist_ref.append(l)

    tf.set_random_seed(0)
    tf.get_default_session().run(tf.global_variables_initializer())

    var_list = [a, b]
    lossandgrad = U.function([], [loss, U.flatgrad(loss, var_list)])
    adam = MpiAdam(var_list)

    losslist_test = []
    for i in range(10):
        l, g = lossandgrad()
        adam.update(g, stepsize)
        print(i, l)
        losslist_test.append(l)

    np.testing.assert_allclose(np.array(losslist_ref), np.array(losslist_test), atol=1e-4)


if __name__ == "__main__":
    test_MpiAdam()
