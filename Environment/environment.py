
"""Vehicular Network Environments."""
import dm_env
from dm_env import specs
from acme.types import NestedSpec
import numpy as np
from typing import List, Tuple, NamedTuple
import Environment.environmentConfig as env_config
from Environment.dataStruct import timeSlots, taskList, edgeList, vehicleList, edgeAction
from Environment.utilities import rescale_the_list_to_small_than_one, generate_channel_fading_gain, compute_channel_condition, compute_transmission_rate, compute_SINR

class vehicularNetworkEnv(dm_env.Environment):
    """Vehicular Network Environment built on the dm_env framework."""
    
    def __init__(
        self, 
        envConfig: env_config.vehicularNetworkEnvConfig = None) -> None:
        """Initialize the environment."""
        if envConfig is None:
            self._config = env_config.vehicularNetworkEnvConfig()
        else:
            self._config = envConfig

        self._time_slots: timeSlots = timeSlots(
            start=self._config.time_slot_start,
            end=self._config.time_slot_end,
            slot_length=self._config.time_slot_length,
        )
        
        self._task_list: taskList = taskList(
            task_number=self._config.task_number,
            minimum_data_size=self._config.minimum_data_size,
            maximum_data_size=self._config.maximum_data_size,
            minimum_computation_cycles=self._config.minimum_computation_cycles,
            maximum_computation_cycles=self._config.maximum_computation_cycles,
            seed=self._config.seed,
        )
        
        self._vehicle_list: vehicleList = vehicleList(
            number=self._config.vehicle_number,
            time_slots=self._time_slots,
            trajectories_file_name=self._config.trajectories_out_file_name,
            slot_number=self._config.time_slot_number,
            task_number=self._config.task_number,
            task_request_rate=self._config.task_request_rate,
            seeds=self._config.vehicle_seeds,
        )
        
        self._edge_list: edgeList = edgeList(
            edge_number=self._config.edge_number,
            power=self._config.edge_power,
            bandwidth=self._config.edge_bandwidth,
            minimum_computing_speed=self._config.edge_minimum_computing_speed,
            maximum_computing_speed=self._config.edge_maximum_computing_speed,
            communication_range=self._config.communication_range,
            map_length=self._config.map_length,
            map_width=self._config.map_width,
            seed=self._config.edge_seed,
        )
        
        self._action_size, self._observation_size, self._reward_size, \
            self._critic_network_action_size = self._define_size_of_spaces()

        self._distance_matrix, self._radio_coverage_matrix, self._config.vehicle_number_within_edges, \
            self._vehicle_index_within_edges, self._maximum_vehicle_number_within_edges = self.init_distance_matrix_and_radio_coverage_matrix()
        
        self._reward: np.ndarray = np.zeros(self._reward_size)
        
        self._occupied_power = np.zeros(shape=(self._config.edge_number, self._config.time_slot_number))
        self._occupied_computing_resources = np.zeros(shape=(self._config.edge_number, self._config.time_slot_number))
        
        self._reset_next_step: bool = True
        
    def _define_size_of_spaces(self) -> Tuple[int, int, int, int]:
        """The action space is transmison power, task assignment, and computing resources allocation"""
        action_size = self._config.max_vehicle_number * 3
        
        """The observation space is the location, task size, computing cycles of each vehicle, then the aviliable transmission power, and computation resoucers"""
        observation_size = self._config.max_vehicle_number * 3 + 2
        
        """The reward space is the reward of each edge node and the gloabl reward
        reward[-1] is the global reward.
        reward[0:edge_number] are the edge rewards.
        """
        reward_size = self._config._edge_number + 1
        
        """Defined the shape of the action space in critic network"""
        critici_network_action_size = self._config._edge_number * action_size
        
        return action_size, observation_size, reward_size, critici_network_action_size
        
    def reset(self) -> dm_env.TimeStep:
        """Resets the state of the environment and returns an initial observation.
        Returns: observation (object): the initial observation of the
            space.
        Returns the first `TimeStep` of a new episode.
        """
        self._time_slots.reset()
        self._occupied_power = np.zeros(shape=(self._config.time_slot_number))
        self._occupied_computing_resources = np.zeros(shape=(self._config.time_slot_number))
        self._reset_next_step = False
        return dm_env.restart(observation=self._observation())

    def step(self, action: np.ndarray):
        """Run one timestep of the environment's dynamics. When end of
        episode is reached, you are responsible for calling `reset()`
        to reset this environment's state.
        """
        
        if self._reset_next_step:
            return self.reset()
        
        edge_actions = self.transform_action_array_to_actions(action)
        self.compute_reward(edge_actions)      
        observation = self._observation()
        
        # check for termination
        if self._time_slots.is_end():
            self._reset_next_step = True
            return dm_env.termination(observation=observation, reward=self._reward)
        self._time_slots.add_time()
        return dm_env.transition(observation=observation, reward=self._reward)

    def transform_action_array_to_actions(self, action: np.ndarray, now_vehicle_numbers: List[int], now_vehicle_indexs: List[List[int]]) -> List[edgeAction]:
        """Transform the action array to the actions of edge nodes.
        Args:
            action: the action of the agent.
                the shape of the action is (edge_number, action_size)
        Returns:
            actions: the list of edge node actions.
        """ 
        
        edge_actions: List[edgeAction] = [
            self.generate_edge_action_from_np_array(
                now_time=self._time_slots.now(),
                edge_index=i,
                maximum_vehicle_number=self._config.max_vehicle_number,
                now_vehicle_number=now_vehicle_numbers[i],
                now_vehicle_index=now_vehicle_indexs[i],
                network_output=action[i, :],
                action_time=self._time_slots.now(),
            ) for i in range(self._config.edge_number)
        ]
        
        return edge_actions

    def compute_reward(
        self,
        edge_action_list: List[edgeAction],
    ) -> None:
        
        self._edge_action_list = edge_action_list        
        
        self._vehicle_SINR = np.zeros((self._config.vehicle_number,))
        self._vehicle_transmission_time = np.zeros((self._config.vehicle_number,))
        self._vehicle_execution_time = np.zeros((self._config.vehicle_number,))
        self._vehicle_wired_transmission_time = np.zeros((self._config.vehicle_number,))
        
        self._vehicle_intar_edge_inference = np.zeros((self._config.vehicle_number,))
        self._vehicle_inter_edge_inference = np.zeros((self._config.vehicle_number,))
        
        self._vehicle_edge_channel_condition = np.zeros((self._config.vehicle_number, self._config.edge_number))
        self._vehicle_edge_transmission_power = np.zeros((self._config.vehicle_number, self._config.edge_number))
        self._vehicle_edge_task_assignment = np.zeros((self._config.vehicle_number, self._config.edge_number))
        self._vehicle_edge_computation_resources = np.zeros((self._config.vehicle_number, self._config.edge_number))
        
        for edge_action in self._edge_action_list:
            edge_index = edge_action.get_edge_index()
            the_edge = self._edge_list.get_edge_by_index(edge_index)
            vehicle_index_within_edge = edge_action.get_now_vehicle_index()
            now_uploading_task_number = 0
            transmission_power_allocation = edge_action.get_transmission_power_allocation()
            task_assignment = edge_action.get_task_assignment()
            now_uploading_vehicles = []
            for vehicle_index in vehicle_index_within_edge:
                requested_task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index).get_requested_task_by_slot_index(self._time_slots.now())
                if requested_task_index != -1:
                    now_uploading_task_number += 1
                    now_uploading_vehicles.append(vehicle_index)
                    self._vehicle_edge_channel_condition[vehicle_index, edge_index] = compute_channel_condition(
                        channel_fading_gain=generate_channel_fading_gain(self._config.mean_channel_fading_gain, self._config.second_moment_channel_fading_gain),
                        distance=self._distance_matrix[vehicle_index][edge_index][self._time_slots.now()],
                        path_loss_exponent=self._config.path_loss_exponent,
                    )
                    
            transmission_power_allocation = rescale_the_list_to_small_than_one(transmission_power_allocation[:now_uploading_task_number])
            for vehicle_index, transmission_power in zip(now_uploading_vehicles, transmission_power_allocation):
                self._vehicle_edge_transmission_power[vehicle_index][edge_index] = transmission_power * (the_edge.get_power() - self._occupied_power[edge_index][self._time_slots.now()])
            task_assignment = task_assignment[:now_uploading_task_number]
            for vehicle_index, task_assignment_value in zip(now_uploading_vehicles, task_assignment):
                processing_edge_index = np.floor(task_assignment_value / (1 / self._config.edge_number))
                self._vehicle_edge_task_assignment[vehicle_index][processing_edge_index] = 1
                if processing_edge_index != edge_index:
                    task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index).get_requested_task_by_slot_index(self._time_slots.now())
                    data_size = self._task_list.get_task_by_index(task_index).get_data_size()
                    self._vehicle_wired_transmission_time[vehicle_index] = data_size / self._config.wired_transmission_rate * self._config.wired_transmission_discount * \
                            the_edge.get_edge_location().get_distance(self._edge_list.get_edge_by_index(processing_edge_index).get_edge_location())
                
        for edge_action in self._edge_action_list:
            edge_index = edge_action.get_edge_index()
            the_edge = self._edge_list.get_edge_by_index(edge_index)
            computation_resource_allocation = edge_action.get_computing_resource_allocation()
            task_assignment_number = self._vehicle_edge_task_assignment[:, edge_index].sum()
            computation_resource_allocation = rescale_the_list_to_small_than_one(computation_resource_allocation[:task_assignment_number])
            for vehicle_index, computation_resource in zip(np.where(self._vehicle_edge_task_assignment[:, edge_index] == 1)[0], computation_resource_allocation):
                self._vehicle_edge_computation_resources[vehicle_index][edge_index] = computation_resource * (the_edge.get_computing_speed() - self._occupied_computing_resources[edge_index][self._time_slots.now()])

        """Compute the execution time"""
        for vehicle_index in range(self._config.vehicle_number):
            for edge_index in range(self._config.edge_number):
                if self._vehicle_edge_task_assignment[vehicle_index][edge_index] == 1:
                    the_edge = self._edge_list.get_edge_by_index(edge_index)
                    task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index).get_requested_task_by_slot_index(self._time_slots.now())
                    data_size = self._task_list.get_task_by_index(task_index).get_data_size()
                    computation_cycles = self._task_list.get_task_by_index(task_index).get_computation_cycles()
                    self._vehicle_execution_time[vehicle_index] = float(data_size * computation_cycles / self._vehicle_edge_computation_resources[vehicle_index][edge_index])
                    occupied_time = np.floor(data_size * computation_cycles / self._vehicle_edge_computation_resources[vehicle_index][edge_index])
                    if occupied_time > 0:
                        if self._time_slots.now() + self._config.slot_number < self._config.slot_number:
                            for i in range(int(self._config.slot_number)):
                                self._occupied_computing_resources[edge_index][self._time_slots.now() + i] += self._vehicle_edge_computation_resources[vehicle_index][edge_index]
                        else:
                            for i in range(int(self._config.slot_number - self._time_slots.now())):
                                self._occupied_computing_resources[edge_index][self._time_slots.now() + i] += self._vehicle_edge_computation_resources[vehicle_index][edge_index]
                    
        """Compute the inference"""
        for edge_index in range(self._config.edge_number):
            for vehicle_index in range(self._config.vehicle_number):
                if self._vehicle_edge_transmission_power[vehicle_index][edge_index] != 0:
                    """Compute the intar edge inference"""
                    the_channel_condition = self._vehicle_edge_channel_condition[vehicle_index][edge_index]
                    for other_vehicle_index in range(self._config.vehicle_number):
                        if other_vehicle_index != vehicle_index and self._vehicle_edge_transmission_power[other_vehicle_index][edge_index] != 0 and self._vehicle_edge_channel_condition[other_vehicle_index][edge_index] < the_channel_condition:
                            self._vehicle_intar_edge_inference[vehicle_index] += self._vehicle_edge_channel_condition[other_vehicle_index][edge_index] * self._vehicle_edge_transmission_power[other_vehicle_index][edge_index]
                    """Compute the inter edge inference"""
                    for other_edge_index in range(self._config.edge_number):
                        if other_edge_index != edge_index:
                            for other_vehicle_index in range(self._config.vehicle_number):
                                if self._vehicle_edge_transmission_power[other_edge_index][other_edge_index] != 0:
                                    self._vehicle_inter_edge_inference[vehicle_index] += compute_channel_condition(
                                        generate_channel_fading_gain(self._config.mean_channel_fading_gain, self._config.second_moment_channel_fading_gain),
                                        self._distance_between_vehicle_and_edge[other_vehicle_index, edge_index],
                                        self._config.path_loss_exponent,
                                    ) * self._vehicle_edge_transmission_power[other_vehicle_index][other_edge_index]
        
        """Compute the SINR and transimission time"""
        for vehicle_index in range(self._config.vehicle_number):
            for edge_index in range(self._config.edge_number):
                if self._vehicle_edge_transmission_power[vehicle_index][edge_index] != 0:
                    task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index).get_requested_task_by_slot_index(self._time_slots.now())
                    data_size = self._task_list.get_task_by_index(task_index).get_data_size()
                    self._vehicle_SINR[vehicle_index] = compute_SINR(
                        white_gaussian_noise=self._config.white_gaussian_noise, 
                        channel_condition=self._vehicle_edge_channel_condition[vehicle_index][edge_index],\
                        transmission_power=self._vehicle_edge_transmission_power[vehicle_index][edge_index],
                        intra_edge_interference=self._vehicle_intar_edge_inference[vehicle_index],
                        inter_edge_interference=self._vehicle_inter_edge_inference[vehicle_index],)
                    transmission_rate = compute_transmission_rate(
                        SINR=self._vehicle_SINR[vehicle_index], 
                        bandwidth=self._config.edge_bandwidth)
                    self._vehicle_transmission_time[vehicle_index] = float(data_size / transmission_rate)
                    occupied_time = np.floor(data_size / transmission_rate)
                    if occupied_time > 0:
                        if self._time_slots.now() + occupied_time < self._config.slot_number:
                            for i in range(int(occupied_time)):
                                self._occupied_power[edge_index][self._time_slots.now() + i] += self._vehicle_edge_transmission_power[vehicle_index][edge_index]
                        else:
                            for i in range(int(self._config.slot_number - self._time_slots.now())):
                                self._occupied_power[edge_index][self._time_slots.now() + i] += self._vehicle_edge_transmission_power[vehicle_index][edge_index]
        
        self._reward[-1] = - (np.sum(self._vehicle_transmission_time) + np.sum(self._vehicle_wired_transmission_time) + np.sum(self._vehicle_execution_time))
        
        for edge_index in range(self._config.edge_number):
            edge_reward = 0
            for vehicle_index in self._vehicle_index_within_edges[edge_index][self._time_slots.now()]:
                requested_task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index).get_requested_task_by_slot_index(self._time_slots.now())
                if requested_task_index != -1:
                    edge_reward += self._vehicle_edge_transmission_power / self._vehicle_intar_edge_inference[vehicle_index] - self._vehicle_wired_transmission_time() - self._vehicle_execution_time()
                    
            self._reward[edge_index] = edge_reward

    """Define the action spaces of edge in critic network."""
    def critic_network_action_spec(self) -> specs.BoundedArray:
        """Define and return the action space."""
        critic_network_action_shape = (self._config.edge_number, self._critic_network_action_size)
        return specs.BoundedArray(
            shape=(critic_network_action_shape),
            dtype=float,
            minimum=np.zeros(critic_network_action_shape),
            maximum=np.ones(critic_network_action_shape),
            name='critic_actions',
        )

    """Define the gloabl observation spaces."""
    def observation_spec(self) -> specs.BoundedArray:
        """Define and return the observation space."""
        observation_shape = (self._config.edge_number, self._observation_size)
        return specs.BoundedArray(
            shape=observation_shape,
            dtype=float,
            minimum=np.zeros(observation_shape),
            maximum=np.ones(observation_shape),
            name='observations'
        )
    
    """Define the gloabl action spaces."""
    def action_spec(self) -> specs.BoundedArray:
        """Define and return the action space."""
        action_shape = (self._config.edge_number, self._action_size)
        return specs.BoundedArray(
            shape=action_shape,
            dtype=float,
            minimum=np.zeros(action_shape),
            maximum=np.ones(action_shape),
            name='actions'
        )

    def reward_spec(self):
        """Define and return the reward space."""
        return specs.Array(
            shape=(self._reward_size,), 
            dtype=float, 
            name='rewards'
        )
    
    def _observation(self) -> np.ndarray:
        """Return the observation of the environment."""
        """
        observation_shape = (self._config.edge_number, self._observation_size)
        The observation space is the location, task size, and computation cycles of each vehicle, then the aviliable transmission power, and computation resoucers
        """
        observation = np.zeros((self._config.edge_number, self._observation_size,))
        for j in range(self._config.edge_number):
            vehicle_number_in_edge = self._config.vehicle_number_within_edges[j][self._time_slots.now()]
            index = 0
            for i in range(vehicle_number_in_edge):
                vehicle_index = self._vehicle_index_within_edges[j][self._time_slots.now()][i]
                distance = self._distance_matrix[vehicle_index][j][self._time_slots.now()]
                task_index = self._vehicle_list.get_vehicle_by_index(vehicle_index=vehicle_index).get_requested_task_by_slot_index(slot_index=self._time_slots.now())
                data_size = self._task_list.get_task_by_index(task_index=task_index).get_data_size()
                computing_cycles = self._task_list.get_task_by_index(task_index=task_index).get_computation_cycles()
                observation[j][index] = float(distance / self._config.communication_range)
                index += 1
                observation[j][index] = float(data_size / self._config.task_maximum_data_size)
                index += 1
                observation[j][index] = float(computing_cycles / self._config.task_maximim_computation_cycles)
            observation[j][-2] = self._occupied_power[j][self._time_slots.now()]
            observation[j][-1] = self._occupied_computing_resources[j][self._time_slots.now()]
        return observation

    def init_distance_matrix_and_radio_coverage_matrix(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[List[List[int]]], int]:
        """Initialize the distance matrix and radio coverage."""
        matrix_shpae = (self._config.vehicle_number, self._config.edge_number, self._config.time_slot_number)
        distance_matrix = np.zeros(matrix_shpae)
        radio_coverage_matrix = np.zeros(matrix_shpae)
        
        """Get the radio coverage information of each edge node."""
        vehicle_number_within_edges = np.zeros((self._config.edge_number, self._config.time_slot_number))
        vehicle_index_within_edges = [[[] for __ in range(self._config.time_slot_number)] for _ in range(self._config.edge_number)]

        for i in range(self._config.vehicle_number):
            for j in range(self._config.edge_number):
                for k in range(self._config.time_slot_number):
                    distance_matrix[i][j][k] = self._vehicle_list.get_vehicle_by_index(i).get_distance_between_edge(k, self._edge_list.get_edge_by_index(j).get_edge_location())
                    if distance_matrix[i][j][k] <= self._config.communication_range:
                        radio_coverage_matrix[i][j][k] = 1
                        vehicle_number_within_edges[j][k] += 1
                        vehicle_index_within_edges[j][k].append(i)
        return distance_matrix, radio_coverage_matrix, vehicle_number_within_edges, vehicle_index_within_edges, np.max(vehicle_number_within_edges)
    
        
    def generate_edge_action_from_np_array(
        self, 
        now_time: int,
        edge_index: int,
        maximum_vehicle_number: int,
        now_vehicle_number: int,
        now_vehicle_index: List[int],
        network_output: np.ndarray,
        action_time: int) -> edgeAction:
        """ generate the edge action from the neural network output.
        Args:
            network_output: the output of the neural network.
        Returns:
            the edge action.
        """
        
        edge_action = edgeAction(
            edge_index=edge_index,
            now_time=now_time,
            maximum_vehicle_number=maximum_vehicle_number,
            now_vehicle_number=now_vehicle_number,
            now_vehicle_index=now_vehicle_index,
            transmission_power_allocation=network_output[: maximum_vehicle_number],
            task_assignment=network_output[maximum_vehicle_number : maximum_vehicle_number * 2],
            computation_resource_allocation=network_output[maximum_vehicle_number * 2 :],
            action_time=action_time,
        )

        return edge_action


Array = specs.Array
BoundedArray = specs.BoundedArray
DiscreteArray = specs.DiscreteArray


class EnvironmentSpec(NamedTuple):
    """Full specification of the domains used by a given environment."""
    observations: NestedSpec
    critic_actions: NestedSpec
    actions: NestedSpec
    rewards: NestedSpec
    discounts: NestedSpec


def make_environment_spec(environment: vehicularNetworkEnv) -> EnvironmentSpec:
    """Returns an `EnvironmentSpec` describing values used by an environment."""
    return EnvironmentSpec(
        observations=environment.observation_spec(),
        critic_actions=environment.critic_network_action_spec(),
        actions=environment.action_spec(),
        rewards=environment.reward_spec(),
        discounts=environment.discount_spec())