import copy
import json
import math
import random
import time

from loguru import logger

from simfleet.planner.constants import CONFIG_FILE, ACTIONS_FILE, \
    ROUTES_FILE, get_benefit, get_travel_cost, get_charge_cost
from simfleet.planner.generators_utils import has_enough_autonomy, calculate_km_expense
from simfleet.planner.plan import JointPlan, Plan
from simfleet.planner.planner import Planner, meters_to_seconds, Node


def fill_statistics(action, current_pos=None, current_autonomy=None, agent_max_autonomy=None, routes_dic=None):
    if action.get('type') == 'PICK-UP':
        # distance from transport position to customer origin
        p1 = current_pos
        p2 = action.get('attributes').get('customer_origin')
        route = get_route(routes_dic, p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'MOVE-TO-DEST':
        # distance from customer_origin to customer_destination
        p1 = action.get('attributes').get('customer_origin')
        p2 = action.get('attributes').get('customer_dest')
        route = get_route(routes_dic, p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'MOVE-TO-STATION':
        # distance from transport position to station position
        p1 = current_pos
        p2 = action.get('attributes').get('station_position')
        route = get_route(routes_dic, p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'CHARGE':
        need = agent_max_autonomy - current_autonomy
        total_time = need / action.get('attributes').get('power')
        # time to complete the charge
        action['statistics']['time'] = total_time
        # amount (of something) to charge
        action['statistics']['need'] = need

    return action


def get_route(routes_dic, p1, p2):
    key = str(p1) + ":" + str(p2)
    route = routes_dic.get(key)
    if route is None:
        # En el futur, demanar la ruta al OSRM
        logger.info("ERROR :: There is no route for key \"", key, "\" in the routes_dic")
        exit()
    return route


class GoalFixer:

    def __init__(self):
        self.config_dic = None
        self.actions_dic = None
        self.routes_dic = None
        self.joint_plan = None
        self.agents = None

        self.initial_plan = {}
        self.agent_goal = {}
        self.fixed_goals = {}
        self.plan_node = {}
        self.current_plan = {}

    # Load dictionary data
    def initialize(self):
        try:
            f2 = open(CONFIG_FILE, "r")
            self.config_dic = json.load(f2)

            f2 = open(ACTIONS_FILE, "r")
            self.actions_dic = json.load(f2)

            f2 = open(ROUTES_FILE, "r")
            self.routes_dic = json.load(f2)

        except Exception as e:
            print(str(e))
            exit()

    # Creates Transport Agents that will act as players in the Best Response game
    def create_agents(self):
        agents = []
        for agent in self.config_dic.get('transports'):
            agent_id = agent.get('name')
            agent_dic = {
                'id': agent_id,
                'initial_position': agent.get('position'),
                'max_autonomy': agent.get('autonomy'),
                'current_autonomy': agent.get('current_autonomy')
            }
            agents.append(agent_dic)

            self.initial_plan[agent_id] = None
            self.agent_goal[agent_id] = None
            self.fixed_goals[agent_id] = []
            self.plan_node[agent_id] = None
            self.current_plan[agent_id] = None

        self.agents = agents

        logger.debug(f"Agents loaded {self.agents}")

    def reload_agents(self):
        agents = []
        for agent in self.config_dic.get('transports'):
            agent_id = agent.get('name')
            agent_dic = {
                'id': agent_id,
                'initial_position': agent.get('position'),
                'max_autonomy': agent.get('autonomy'),
                'current_autonomy': agent.get('current_autonomy')
            }
            agents.append(agent_dic)
        self.agents = agents

    # Prepares the data structure to store the Joint plan
    def init_joint_plan(self):
        # Initialize joint plan to None
        self.joint_plan = {"no_change": {}, "joint": None, "table_of_goals": {}, "individual": {}}
        # Create an empty plan per transport agent
        for a in self.agents:
            key = a.get('id')
            self.joint_plan["individual"][key] = None
            # To indicate end of best response process
            self.joint_plan["no_change"][key] = False

        # Initialize table_of_goals
        for customer in self.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = (None, math.inf)

    # Given a transport agent, creates its associated Planner object
    def create_planner(self, agent):
        # prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                agent_id=agent.get('id'),
                                agent_pos=agent.get('initial_position'),
                                agent_max_autonomy=agent.get('max_autonomy'),
                                agent_autonomy=agent.get('current_autonomy'),
                                previous_plan=None, joint_plan=self.joint_plan, blackboard=self.blackboard)
        return agent_planner

    # Returns true if the transport agent has an individual plan in the joint plan
    def has_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id')) is not None

    # Returns a transport agent's individual plan
    def get_individual_plan(self, agent):
        return self.joint_plan.get('individual').get(agent.get('id'))

    # Calculates the utility of an individual plan w.r.t. the actions and goals in the Joint plan
    def evaluate_plan(self, plan, initial_plan=False):
        # Benefits
        benefits = 0
        for entry in plan.entries:
            action = entry.action
            if action.get('type') == 'MOVE-TO-DEST':
                # CHECK IF I'M THE FIRST ONE PICKING THAT CUSTOMER UP
                plan_owner = action.get('agent')
                customer = action.get('attributes').get('customer_id')
                tup = self.joint_plan.get('table_of_goals').get(customer)
                # if no one is serving the transport
                if tup[0] is None and initial_plan:
                    # only accept this as valid when evaluating the initial plans proposed by feasible_joint_plan()
                    # since they have to be evaluated before updating the joint plan
                    benefits += get_benefit(action)
                else:
                    serving_transport = tup[0]
                    if serving_transport == plan_owner:
                        benefits += get_benefit(action)
        # Costs
        costs = 0
        for entry in plan.entries:
            action = entry.action
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
                costs += get_travel_cost(action)
            # For actions that entail charging, pay for the charged electricity
            # TODO price increase if congestion (implementar a futur)
            else:
                costs += get_charge_cost(action)
        # Utility (or g value) = benefits - costs
        utility = benefits - costs
        if utility < 0:
            logger.error("THE COSTS ARE HIGHER THAN THE BENEFITS")

        return utility

    # Joins the actions of all individual plans and orders them to create the joint plan
    def extract_joint_plan(self):
        all_entries = []
        for transport in self.joint_plan.get('individual').keys():
            plan = self.joint_plan.get('individual').get(transport)
            if plan is None:
                continue
            for entry in plan.entries:
                all_entries.append(entry)

        # Order actions by init_time
        all_entries.sort(key=lambda x: x.init_time)
        self.joint_plan["joint"] = JointPlan(all_entries)

    # Given a transport agent and a plan associated to it, substitutes the agent individual plan with the new plan
    # and modifies the contents of the joint_plan accordingly
    def update_joint_plan(self, agent_id, new_plan):
        # Update agent's individual plan
        self.joint_plan["individual"][agent_id] = new_plan
        # self.joint_plan["no_change"][agent_id] = False
        # Extract every individual plan action to build the joint plan
        self.extract_joint_plan()
        # Update table_of_goals to match with individual plans
        self.update_table_of_goals()

    def update_table_of_goals(self):
        # Restart table of table_of_goals
        for customer in self.config_dic.get("customers"):
            customer_id = customer.get('name')
            self.joint_plan["table_of_goals"][customer_id] = (None, math.inf)
        aux = {}

        for entry in self.joint_plan.get("joint").entries:
            action = entry.action
            if action.get('type') == 'PICK-UP':
                agent = action.get('agent')
                customer = action.get('attributes').get('customer_id')
                pick_up_time = entry.end_time
                if aux.get(customer) is None:
                    aux[customer] = []
                # for each customer, add tuples with every transport that serves him with pick-up time
                aux[customer].append((agent, pick_up_time))

        # Then, compare all pick up times for a single customer and decide which transport arrives before
        for customer in aux.keys():
            earliest = min(aux.get(customer), key=lambda x: x[1])
            # Input in the table of goals a tuple with the serving transport id and pick-up time
            self.joint_plan['table_of_goals'][customer] = earliest

    # Checks stopping criteria of Best Response algorithm
    def stop(self):
        res = 0
        for agent_id in self.fixed_goals.keys():
            fixed_goals = self.fixed_goals[agent_id]
            if fixed_goals is not None:
                for tup in fixed_goals:
                    res += 1
        return res == len(self.config_dic.get('customers'))

    def check_update_joint_plan(self, agent_id, prev_plan, new_plan):

        # Case 1) Agent finds no plan or a plan with negative utility (only costs)
        if new_plan is None:
            # if both the previous and new plans where None, indicate that the agent did not change its proposal
            if prev_plan is None:
                logger.error(
                    f"Agent {agent_id} could not find any plan"
                )
                self.update_joint_plan(agent_id, new_plan)
                logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.joint_plan["no_change"][agent_id] = True

            else:
                # the planner did not find any feasible plan (utility of prev plan was negative but planner returned None)
                if prev_plan.utility < 0:
                    logger.error(
                        f"Agent {agent_id} could not find any plan"
                    )
                    self.update_joint_plan(agent_id, new_plan)
                    logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                    self.joint_plan["no_change"][agent_id] = False

                # TODO compare plans action by action not just by their utility
                # the planner found the same plan as before (utility of prev plan was positive but planner retuned None)
                else:
                    # logger.error(
                    #     f"Agent {agent_id} could not find any plan"
                    # )
                    # self.update_joint_plan(agent_id, new_plan)
                    # logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                    # self.joint_plan["no_change"][agent_id] = False
                    # logger.critical("NO DEURIA ENTRAR ACÍ")
                    logger.error(
                        f"Agent {agent_id} could not improve its previous plan (it found the same one than in the previous round)")
                    self.joint_plan["no_change"][agent_id] = True

        # Planner returns something that is not NONE
        else:
            new_utility = new_plan.utility
            # if the prev_plan was None (either 1st turn or couldn't find plan last round) accept new plan
            if prev_plan is None:
                logger.warning(
                    f"Agent {agent_id} found a plan with utility {new_utility:.4f}")
                logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = False
            # Case 2) Agent finds a new plan that improves its utility
            elif not new_plan.equals(prev_plan):  # != prev_plan.utility:
                logger.warning(
                    f"Agent {agent_id} found new plan with utility {new_utility:.4f}")
                logger.debug(f"Updating agent's {agent_id} plan in the joint_plan")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = False

            # Case 3) Agent finds the same plan it had proposed before
            elif new_plan.equals(prev_plan):
                logger.critical("NO DEURIA ENTRAR ACÍ")
                logger.info(
                    f"Agent {agent_id} could not find a better plan (it found the same one than in the previous round)")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = True

    def print_game_state(self):
        # joint_plan = {"no_change": {}, "joint": None, "table_of_goals": {}, "individual": {}}
        logger.debug("\n")
        logger.debug("#########################################################################")
        logger.debug("CURRENT GAME STATE")

        logger.debug("\n")
        logger.debug("Individual plans:")
        for agent in self.joint_plan.get('individual').keys():
            plan = self.joint_plan.get('individual').get(agent)
            if plan is None:
                logger.debug(f"{agent:20s} : NO PLAN")
            else:
                logger.debug(f"{agent:20s} : Plan with {len(plan.entries):2d} entries and utility {plan.utility:.4f}")
                logger.debug(plan.to_string_plan())

        logger.debug("\n")
        logger.debug("Joint plan:")
        if self.joint_plan.get("joint") is None:
            logger.debug("NO PLAN")
        else:
            logger.debug(self.joint_plan.get("joint").print_plan())

        logger.debug("\n")
        logger.debug("Table of goals:")
        for customer in self.joint_plan.get('table_of_goals').keys():
            logger.debug(f"{customer:20s} : {self.joint_plan.get('table_of_goals').get(customer)}")

        # logger.debug("\n")
        # logger.debug("No change in plan:")
        # for agent in self.joint_plan.get('no_change').keys():
        #     logger.debug(f"{agent:20s} : {self.joint_plan.get('no_change').get(agent)}")

        logger.debug("#########################################################################")

    def fixed_customers(self, agent_id):
        aux = []
        for tup in self.fixed_goals[agent_id]:
            aux.append(tup[0])
        return aux

    def obtain_best_plans(self):
        for agent in self.agents:
            agent_id = agent.get('id')
            logger.info(f"Agent \'{agent_id}\''s turn")
            logger.info("-------------------------------------------------------------------------")
            logger.info(f"Creating first plan for agent {agent_id}")
            # prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
            agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                    agent_id=agent.get('id'),
                                    agent_pos=agent.get('initial_position'),
                                    agent_max_autonomy=agent.get('max_autonomy'),
                                    agent_autonomy=agent.get('current_autonomy'),
                                    previous_plan=None, joint_plan={}, blackboard={})
            agent_planner.run()
            new_plan = agent_planner.plan
            self.initial_plan[agent_id] = new_plan
            logger.info(new_plan.to_string_plan())

        # for agent_id in self.initial_plan.keys():
        #     self.check_update_joint_plan(agent_id, None, self.initial_plan[agent_id])

    def fix_goals_initialization(self):
        for agent in self.agents:
            agent_id = agent.get('id')
            if self.initial_plan[agent_id] is not None:
                # Get first goal from each agent plan
                aux = self.initial_plan[agent_id]
                for entry in aux.entries:
                    action = entry.action
                    if action.get('type') == 'PICK-UP':
                        customer = action.get('attributes').get('customer_id')
                        pick_up_time = entry.end_time
                        # Save serving customer and pick-up time:
                        self.agent_goal[agent_id] = (customer, pick_up_time)
                        logger.info(f"Goal {self.agent_goal[agent_id]} temporarily stored for agent {agent_id}")
                        break

        # Check for conflicts
        conflict = False
        for agent1 in self.agents:
            agent1_id = agent1.get('id')
            goal1 = self.agent_goal[agent1_id]
            if goal1 is not None:
                for agent2 in self.agents:
                    agent2_id = agent2.get('id')
                    if agent2_id != agent1_id:
                        goal2 = self.agent_goal[agent2_id]

                        if goal2 is not None:
                            # if the customers equal there is a conflict
                            if goal1[0] == goal2[0]:
                                logger.info(f"Detected conflict between agents {agent1_id} and {agent2_id} "
                                            f"with goals {goal1} and goal{2}")
                                conflict = True
                                if goal1[1] <= goal2[1]:
                                    logger.info(f"Agent {agent1_id} keeps the goal")
                                    self.agent_goal[agent2_id] = None
                                else:
                                    logger.info(f"Agent {agent2_id} keeps the goal")
                                    self.agent_goal[agent1_id] = None

        for agent_id in self.agent_goal.keys():
            if self.agent_goal[agent_id] is not None:
                self.fixed_goals[agent_id].append(self.agent_goal[agent_id])
                logger.info(f'Fixing goal {self.agent_goal[agent_id]} for agent {agent_id}')
                # Clean agent_goal and initial_plan
                self.agent_goal[agent_id] = None
                self.initial_plan[agent_id] = None

        return conflict

    def fix_goals(self):
        for agent in self.agents:
            agent_id = agent.get('id')
            if self.current_plan[agent_id] is not None:
                # Get first goal from each agent plan
                aux = self.current_plan[agent_id]
                for entry in aux.entries:
                    action = entry.action
                    if action.get('type') == 'PICK-UP':
                        customer = action.get('attributes').get('customer_id')
                        pick_up_time = entry.end_time
                        if customer not in self.fixed_customers(agent_id):
                            # Save serving customer and pick-up time:
                            self.agent_goal[agent_id] = (customer, pick_up_time)
                            logger.info(f"Goal {self.agent_goal[agent_id]} temporarily stored for agent {agent_id}")
                            break

        # Check for conflicts
        conflict = False
        for agent1 in self.agents:
            agent1_id = agent1.get('id')
            goal1 = self.agent_goal[agent1_id]
            if goal1 is not None:
                for agent2 in self.agents:
                    agent2_id = agent2.get('id')
                    if agent2_id != agent1_id:
                        goal2 = self.agent_goal[agent2_id]

                        if goal2 is not None:
                            # if the customers equal there is a conflict
                            if goal1[0] == goal2[0]:
                                logger.info(f"Detected conflict between agents {agent1_id} and {agent2_id} "
                                            f"with goals {goal1} and {goal2}")
                                conflict = True
                                if goal1[1] <= goal2[1]:
                                    logger.info(f"Agent {agent1_id} keeps the goal")
                                    self.agent_goal[agent2_id] = None
                                else:
                                    logger.info(f"Agent {agent2_id} keeps the goal")
                                    self.agent_goal[agent1_id] = None

        for agent_id in self.agent_goal.keys():
            if self.agent_goal[agent_id] is not None:
                self.fixed_goals[agent_id].append(self.agent_goal[agent_id])
                logger.info(f'Fixing goal {self.agent_goal[agent_id]} for agent {agent_id}')
                # Clean agent_goal and initial_plan
                self.agent_goal[agent_id] = None
                self.current_plan[agent_id] = None

        return conflict

    def check_conflicts_initialization(self):
        conflict = False
        amount = 0
        for agent_id in self.fixed_goals.keys():
            if self.initial_plan[agent_id] is not None:
                conflict = True
                amount += 1
                logger.info(f'Agent {agent_id} does not have a goal')
        return conflict, amount

    def check_conflicts(self):
        conflict = False
        amount = 0
        for agent_id in self.current_plan.keys():
            if self.current_plan[agent_id] is not None:
                conflict = True
                amount += 1
                logger.info(f'Agent {agent_id} does not have a goal')
        return conflict, amount

    def solve_conflicts_initialization(self):
        agents_in_conflict = []
        # Add agents without goal to agents in conflict
        for agent in self.agents:
            agent_id = agent.get('id')
            if self.fixed_goals[agent_id] is None:
                agents_in_conflict.append(agent)

        # Solve conflicts:
        for agent in agents_in_conflict:
            agent_id = agent.get('id')
            logger.info("-------------------------------------------------------------------------")
            logger.info(f"Creating alternative first plan for agent {agent_id}")
            agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                    agent_id=agent.get('id'),
                                    agent_pos=agent.get('initial_position'),
                                    agent_max_autonomy=agent.get('max_autonomy'),
                                    agent_autonomy=agent.get('current_autonomy'),
                                    previous_plan=None, joint_plan=self.joint_plan, blackboard={})
            agent_planner.run()
            new_plan = agent_planner.plan
            self.initial_plan[agent_id] = new_plan
            logger.info(new_plan.to_string_plan())

    def solve_conflicts(self):
        agents_in_conflict = []
        # Add agents that did not get their current plan deleted
        for agent in self.agents:
            agent_id = agent.get('id')
            if self.current_plan[agent_id] is not None:
                agents_in_conflict.append(agent)

        # Solve conflicts:
        for agent in agents_in_conflict:

            agent_id = agent.get('id')
            logger.info("-------------------------------------------------------------------------")
            logger.info(f"Creating alternative plan for agent {agent_id}")
            agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                    agent_id=agent.get('id'),
                                    agent_pos=agent.get('initial_position'),
                                    agent_max_autonomy=agent.get('max_autonomy'),
                                    agent_autonomy=agent.get('current_autonomy'),
                                    previous_plan=None, joint_plan=self.joint_plan, blackboard={},
                                    start_node=self.plan_node[agent_id])
            agent_planner.plan_from_node()
            new_plan = agent_planner.plan
            self.current_plan[agent_id] = new_plan
            logger.info(f"Current plan for agent {agent_id}:")
            logger.info(new_plan.to_string_plan())

    def fill_tog_with_fixed_goals(self):
        for agent_id in self.fixed_goals.keys():
            if len(self.fixed_goals[agent_id]) > 0:
                for goal in self.fixed_goals[agent_id]:
                    customer = goal[0]
                    pick_up_time = goal[1]
                    # Add fixed goal to the table_of_goals
                    self.joint_plan['table_of_goals'][customer] = (customer, pick_up_time)

        logger.debug(f'Table of goals updated with new fixed goals')
        logger.debug("\n")
        logger.debug("Table of goals:")
        for customer in self.joint_plan.get('table_of_goals').keys():
            logger.debug(f"{customer:20s} : {self.joint_plan.get('table_of_goals').get(customer)}")

    def print_fixed_goals(self):
        logger.debug("\n")
        logger.debug("Fixed goals:")
        for agent_id in self.fixed_goals.keys():
            logger.debug(f"{agent_id:20s} : {self.fixed_goals[agent_id]}")

    def solve_fixed_goals(self, agent, fixed_goals):
        logger.info(f"Creating plan for agent {agent.get('id')}")

        # Get actions
        dic_file = open(ACTIONS_FILE, "r")
        actions_dic = json.load(dic_file)
        agent_actions = actions_dic.get(agent.get('id'))

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        # Turn goals from tuples into customers
        goals = []
        for tuple in fixed_goals:
            goals.append(tuple[0])
        completed_goals = goals.copy()

        actions = []
        completed_goals = []
        logger.info(f"Initial goals for agent {agent.get('id')}: {goals}")

        while goals:
            # Get agent attributes
            current_position = agent.get('initial_position')
            current_autonomy = agent.get('current_autonomy')
            max_autonomy = agent.get('max_autonomy')
            if not actions:
                current_time = 0
            else:
                current_time = sum([a.get('statistics').get('time') for a in actions])

            # Extract customer
            customer = goals.pop(0)
            # customer = goals
            # Get customer actions
            action1 = [a for a in pick_up_actions if a.get('attributes').get('customer_id') == customer]
            action1 = action1[0]
            action2 = [a for a in move_to_dest_actions if a.get('attributes').get('customer_id') == customer]
            action2 = action2[0]

            # Fill statistics w.r.t. current position and autonomy
            action1 = fill_statistics(action1, current_pos=current_position, routes_dic=self.routes_dic)
            action2 = fill_statistics(action2, routes_dic=self.routes_dic)

            # Check autonomy, go to charge in closest station if necessary
            customer_origin = action1.get("attributes").get("customer_origin")
            customer_dest = action2.get("attributes").get("customer_dest")

            if not has_enough_autonomy(current_autonomy, current_position, customer_origin, customer_dest):
                # Store customer in the open goals list again
                goals.insert(0, customer)

                # Get closest station to transport
                station_actions = [fill_statistics(a, current_pos=current_position, routes_dic=self.routes_dic) for
                                   a in
                                   move_to_station_actions]
                action1 = min(station_actions, key=lambda x: x.get("statistics").get("time"))
                station_id = action1.get('attributes').get('station_id')

                # Get actions for that station and fill statistics w.r.t. current position and autonomy
                action2 = [a for a in charge_actions if a.get('attributes').get('station_id') == station_id]
                action2 = action2[0]

                action2 = fill_statistics(action2, current_autonomy=current_autonomy,
                                          agent_max_autonomy=max_autonomy, routes_dic=self.routes_dic)

                # Update position and autonomy after charge
                agent['initial_position'] = action1.get('attributes').get('station_position')
                agent['current_autonomy'] = max_autonomy

                # Add actions to action list
                actions += [action1, action2]

            else:
                # Add actions, update position and autonomy
                # Add actions to action list
                actions += [action1, action2]
                # Update position and autonomy
                agent['current_autonomy'] -= calculate_km_expense(current_position,
                                                                  action2.get('attributes').get('customer_origin'),
                                                                  action2.get('attributes').get('customer_dest'))
                agent['initial_position'] = action2.get('attributes').get('customer_dest')

                # Add served customer to completed_goals
                init = current_time
                pick_up_duration = action1.get('statistics').get('time')
                completed_goals.append(
                    (action2.get('attributes').get('customer_id'), init + pick_up_duration))

        # end of while loop
        agent_id = agent.get('id')
        last_pos = agent.get('initial_position')

        logger.debug(f'Last pos for agent {agent_id} is {last_pos}')

        # Create node from current agent situation
        node = Node()
        node.agent_pos = str(last_pos)
        node.agent_autonomy = agent.get('current_autonomy')
        node.actions = actions

        node.init_time = 0
        node.set_end_time()

        node.value = -1

        node.completed_goals = fixed_goals

        logger.info(f"Planning node for agent {agent.get('id')}:")
        node.print_node()

        self.plan_node[agent.get('id')] = node

        # Create plan with agent action list
        new_plan = Plan(actions, -1, completed_goals)
        utility = self.evaluate_plan(new_plan, initial_plan=True)
        new_plan.utility = utility

        logger.info(f"Agent {agent.get('id')} initial plan:")
        logger.info(new_plan.to_string_plan())

        # Update joint plan for the subsequent planning process
        prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        self.check_update_joint_plan(agent.get('id'), prev_plan, new_plan)

        self.reload_agents()

    def plan_from_fixed_goals(self):
        # Create initial greedy plan that accomplishes fixed goals
        for agent in self.agents:
            self.solve_fixed_goals(agent, self.fixed_goals[agent.get('id')])
        # Use planner to improve the plan if possible
        for agent in self.agents:
            agent_id = agent.get('id')
            logger.info(f"Agent \'{agent_id}\''s turn")
            logger.info("-------------------------------------------------------------------------")
            logger.info(f"Creating plan for agent {agent_id}")
            # prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
            agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                    agent_id=agent.get('id'),
                                    agent_pos=agent.get('initial_position'),
                                    agent_max_autonomy=agent.get('max_autonomy'),
                                    agent_autonomy=agent.get('current_autonomy'),
                                    previous_plan=None, joint_plan=self.joint_plan, blackboard={},
                                    start_node = self.plan_node[agent_id])
            agent_planner.plan_from_node()
            new_plan = agent_planner.plan
            self.current_plan[agent_id] = new_plan
            logger.info(f"Current plan for agent {agent_id}:")
            logger.info(new_plan.to_string_plan())

    def run(self):

        # INITIAL BEST PLANS

        # Read dictionary data
        self.initialize()
        # Create players
        self.create_agents()
        # Initialize data structure
        self.init_joint_plan()
        # Create initial plans from scratch
        self.obtain_best_plans()
        # Fix first goal from each plan
        self.fix_goals_initialization()
        # Fill Table of Goals with non conflicted agent goals
        self.fill_tog_with_fixed_goals()

        # CONFLICT SOLVING PHASE

        # Check how many agents are left without goal
        conflict, amount = self.check_conflicts_initialization()

        while conflict:

            if conflict:
                logger.info(f"There are {amount} agents without a goal")

            # To solve conflicts we 1) update the Table of Goals with the information about fixed goals
            # and make the agents without goal plan again from scratch
            self.solve_conflicts_initialization()
            self.fix_goals_initialization()
            self.fill_tog_with_fixed_goals()

            conflict, amount = self.check_conflicts()

        self.print_game_state()

        i = 0
        while not self.stop():
            i += 1
            logger.debug(f"Iteration {i}")

            logger.debug(f"Planning fixed goals:")
            for agent_id in self.fixed_goals.keys():
                logger.debug(f"{agent_id:20s} : {self.fixed_goals[agent_id]}")

            self.plan_from_fixed_goals()
            # self.print_game_state()
            # exit()
            # Fix first goal from each plan
            self.fix_goals()
            # Fill Table of Goals with non conflicted agent goals
            self.fill_tog_with_fixed_goals()

            # ################################## CONFLICT SOLVING PHASE ####################################
            # Check how many agents are left without goal
            conflict, amount = self.check_conflicts()

            while conflict:

                if conflict:
                    logger.info(f"There are {amount} agents without a goal")

                # To solve conflicts we 1) update the Table of Goals with the information about fixed goals
                # and make the agents without goal plan again from scratch
                self.solve_conflicts()
                self.fix_goals()
                self.fill_tog_with_fixed_goals()

                conflict, amount = self.check_conflicts()


            self.print_game_state()

        logger.info("ALL GOALS ARE MET")
        self.plan_from_fixed_goals()
        self.print_game_state()
        for agent in self.agents:
            agent_id = agent.get('id')
            plan = self.joint_plan.get('individual').get(agent_id)
            utility = self.evaluate_plan(plan)
            logger.info(f"Agent {agent_id} utility: {utility}")



if __name__ == '__main__':
    gf = GoalFixer()
    start = time.time()
    gf.run()
    # br.obtain_best_plans()
    end = time.time()
    logger.debug(f'\tGF process time: {end - start}')
