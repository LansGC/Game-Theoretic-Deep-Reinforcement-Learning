"""Shared helpers for different experiment flavours."""
import dataclasses
from acme.types import NestedSpec
from typing import Sequence, Optional
from acme import types
from acme.tf import networks
from acme.tf import utils as tf2_utils
import numpy as np
import sonnet as snt
from acme.tf import networks as network_utils
from acme.tf import utils
from acme import types


@dataclasses.dataclass
class MAD3PGNetwork:
    """Structure containing the networks for MAD3PG."""
    
    policy_network: types.TensorTransformation
    critic_network: types.TensorTransformation
    observation_network: types.TensorTransformation

    def __init__(
        self,
        policy_network: types.TensorTransformation,
        critic_network: types.TensorTransformation,
        observation_network: types.TensorTransformation,
    ):
        # This method is implemented (rather than added by the dataclass decorator)
        # in order to allow observation network to be passed as an arbitrary tensor
        # transformation rather than as a snt Module.
        self.policy_network = policy_network
        self.critic_network = critic_network
        self.observation_network = utils.to_sonnet_module(observation_network)

    def init(
        self, 
        environment_spec,
    ):
        """Initialize the networks given an environment spec."""
        # Get observation and action specs.
        observation_spec = environment_spec.edge_observations
        critic_action_spec = environment_spec.critic_actions

        # Create variables for the observation net and, as a side-effect, get a
        # spec describing the embedding space.
        emb_spec = utils.create_variables(self.observation_network, [observation_spec])
        
        # Create variables for the policy and critic nets.
        _ = utils.create_variables(self.policy_network, [emb_spec])
        _ = utils.create_variables(self.critic_network, [emb_spec, critic_action_spec])
        

    def make_policy(
        self,
        environment_spec,
        sigma: float = 0.0,
    ) -> snt.Module:
        """Create a single network which evaluates the policy."""
        # Stack the observation and policy networks.

        stacks = [self.observation_network, self.policy_network]

        # If a stochastic/non-greedy policy is requested, add Gaussian noise on
        # top to enable a simple form of exploration.
        # TODO: Refactor this to remove it from the class.
        if sigma > 0.0:
            stacks += [
                network_utils.ClippedGaussian(sigma),
                network_utils.ClipToSpec(environment_spec.edge_actions),   # Clip to action spec.
            ]
                
        # Return a network which sequentially evaluates everything in the stack.
        return snt.Sequential(stacks)


def make_policy_network(
        action_spec,
        policy_layer_sizes: Sequence[int] = (128, 64),
        sigma: float = 0.3,
    ) -> types.TensorTransformation:
        """Creates the networks used by the agent."""

        # Get total number of action dimensions from action spec.
        num_dimensions = np.prod(action_spec.shape, dtype=int)

        # Create the policy network.
        policy_network = snt.Sequential([
            networks.LayerNormMLP(policy_layer_sizes, activate_final=True),
            networks.NearZeroInitializedLinear(num_dimensions),
            network_utils.ClippedGaussian(sigma),
            networks.TanhToSpec(action_spec),
        ])

        return policy_network


def make_default_MAD3PGNetworks(
    action_spec: Optional[NestedSpec] = None,
    policy_layer_sizes: Sequence[int] = (128, 64),
    critic_layer_sizes: Sequence[int] = (256, 128),
    vmin: float = -150.,
    vmax: float = 150.,
    num_atoms: int = 51,
    edge_number: int = 9,
):
    from Agents.MAD4PG.agent import MAD3PGNetwork

    # Get total number of action dimensions from action spec.
    num_dimensions = np.prod(action_spec.shape, dtype=int)

    # Create the shared observation network; here simply a state-less operation.
    observation_network = tf2_utils.batch_concat

    # Create the policy network.
    policy_network = snt.Sequential([
        networks.LayerNormMLP(policy_layer_sizes, activate_final=True),
        networks.NearZeroInitializedLinear(num_dimensions),
        networks.TanhToSpec(action_spec),
    ])

    # Create the critic network.
    critic_network = snt.Sequential([
        # The multiplexer concatenates the observations/actions.
        networks.CriticMultiplexer(),
        networks.LayerNormMLP(critic_layer_sizes, activate_final=True),
        networks.DiscreteValuedHead(vmin, vmax, num_atoms),
    ])

    return MAD3PGNetwork(
        policy_network=policy_network,
        critic_network=critic_network,
        observation_network=observation_network,
    )