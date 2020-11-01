import copy
import json
import math
import random
import time

from loguru import logger

from simfleet.planner.constants import CONFIG_FILE, ACTIONS_FILE, \
    ROUTES_FILE, get_benefit, get_travel_cost, get_charge_cost, TIME_PENALTY
from simfleet.planner.generators_utils import has_enough_autonomy, calculate_km_expense
from simfleet.planner.plan import JointPlan, Plan
from simfleet.planner.planner import Planner, meters_to_seconds

INITIAL_JOINT_PLAN = False
LOOP_DETECTION = True
CONSIDER_PREV_PLAN = False
VERBOSE = 0


def fill_statistics(self, action, current_pos=None, current_autonomy=None, current_time=None):
    if action.get('type') == 'PICK-UP':
        # distance from transport position to customer origin
        p1 = current_pos
        p2 = action.get('attributes').get('customer_origin')
        route = self.get_route(p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'MOVE-TO-DEST':
        # distance from customer_origin to customer_destination
        p1 = action.get('attributes').get('customer_origin')
        p2 = action.get('attributes').get('customer_dest')
        route = self.get_route(p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'MOVE-TO-STATION':
        # distance from transport position to station position
        p1 = current_pos
        p2 = action.get('attributes').get('station_position')
        route = self.get_route(p1, p2)
        dist = route.get('distance')
        time = meters_to_seconds(dist)
        action['statistics']['dist'] = dist
        action['statistics']['time'] = time

    elif action.get('type') == 'CHARGE':

        # Get variables
        agent = action.get('agent')
        station = action.get('attributes').get('station_id')

        # 1. Compute charging time. The charge action will finish at the end of the charging time if there are
        # free places at the station
        need = self.agent_max_autonomy - current_autonomy
        charging_time = need / action.get('attributes').get('power')

        # 2. Check if there will be a free place to charge at the arrival to the station
        available_poles = self.check_available_poles(agent, station, current_time)
        if VERBOSE > 1:
            logger.info(f"Evaluating charge action of agent {agent} in station {station} at time {current_time:.4f}")
            logger.info(f"There are {available_poles} available poles")
        #   2.2 If there is not, compute waiting time, add it to charging time to compute total time
        if available_poles == 0:
            queue, check = self.check_station_queue(agent, station, current_time)
            if VERBOSE > 1:
                logger.info(f"There are {len(queue)} agents in front of {agent}")
            # Get que last X agents of the queue which are in front of you, where X is the number of stations
            # if check, there are more agents in front of me than places in the station
            if check:
                # keep only last X to arrive
                queue = queue[-self.get_station_places(station):]
            # if not check, there are as many agents in front of me as places in the station
            end_times = [x.get('end_charge') for x in queue]
            # Get charge init time
            init_charge = min(end_times)
            # end_charge = init_charge + charging_time
            # Compute waiting time
            waiting_time = init_charge - current_time
            if VERBOSE > 1:
                logger.info(
                    f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:4.f} seconds")
        elif available_poles < 0:
            logger.critical(f"Error computing available poles: {available_poles}")
        # if there are available poles
        else:
            init_charge = current_time
            waiting_time = 0
            if VERBOSE > 1:
                logger.info(f"There are available places")
                logger.info(
                    f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:4.f} seconds")

        # Write times
        #   arrival at the station
        action['statistics']['at_station'] = current_time
        #   begin charging
        action['statistics']['init_charge'] = init_charge
        #   total time
        total_time = charging_time + waiting_time
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


class BestResponse:

    def __init__(self):
        self.config_dic = None
        self.actions_dic = None
        self.routes_dic = None
        self.joint_plan = None
        self.agents = None
        self.list_of_plans = None
        self.list_of_togs = []
        self.best_prev_plan = {}
        self.station_usage = {}

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
        self.list_of_plans = {}
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
            self.list_of_plans[agent_id] = []
            self.best_prev_plan[agent_id] = (0, None)

        self.agents = agents
        self.assign_goals()

        logger.debug(f"Agents loaded {self.agents}")

    def assign_goals(self):
        # List with all customers
        customer_dics = self.config_dic.get('customers')
        customers = []
        for customer in customer_dics:
            customers.append(customer.get('name'))

        # Number of customers each agent will initially pick up
        customers_per_agent = math.ceil(len(customers) / len(self.agents))

        for agent in self.agents:

            if len(customers) >= customers_per_agent:
                # Assign their customers
                goals = random.sample(customers, k=customers_per_agent)
                # TODO hardcoded to repartir 1 2 3
                # goals.append(customers[0])
                # customers.pop(0)
                customers = [c for c in customers if c not in goals]
            else:
                goals = customers.copy()

            agent['goals'] = goals

            logger.info(f"Goals for agent {agent.get('id')}: {goals}")

    def init_station_usage(self):
        for station in self.config_dic.get('stations'):
            self.station_usage[station.get('name')] = []

    # Prepares the data structure to store the Joint plan
    def init_joint_plan(self):
        # Initialize joint plan to None
        self.joint_plan = {"station_usage": None, "no_change": {}, "joint": None,
                           "table_of_goals": {}, "individual": {}}

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

        self.init_station_usage()
        self.joint_plan["station_usage"] = self.station_usage

    # Given a transport agent, creates its associated Planner object
    def create_planner(self, agent):
        # prev_plan = self.joint_plan.get('individual').get(agent.get('id'))
        agent_planner = Planner(self.config_dic, self.actions_dic, self.routes_dic,
                                agent_id=agent.get('id'),
                                agent_pos=agent.get('initial_position'),
                                agent_max_autonomy=agent.get('max_autonomy'),
                                agent_autonomy=agent.get('current_autonomy'),
                                agent_goals=agent.get('goals'),
                                previous_plan=None, joint_plan=self.joint_plan)
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
                if action.get('inv') == 'INV':
                    costs *= 10

            if action.get('type') == 'PICK-UP':
                customer = action.get('attributes').get('customer_id')
                pick_up = self.joint_plan.get('table_of_goals').get(customer)

                # Double check that the customer is being picked up by the agent
                if pick_up[0] != action.get('agent'):
                    logger.critical(f"Agent {action.get('agent')} is being penalized for picking-up customer {customer}"
                                    f"when in the ToG it is being picked up as: {pick_up}")
                # Add waiting time to costs
                costs += pick_up[1] * TIME_PENALTY

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
        # Update station_usage to match with individual plans
        self.update_station_usage()

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

    def update_station_usage(self):
        # Clear station usages
        self.init_station_usage()
        # Extract charge actions from the joint plan
        for entry in self.joint_plan.get("joint").entries:
            action = entry.action
            # Create a usage per CHARGE action
            if action.get('type') == 'CHARGE':
                agent = action.get('agent')
                station = action.get('attributes').get('station_id')
                at_station = entry.init_time
                init_charge = action.get('statistics').get('init_charge')
                end_time = entry.end_time
                inv = action.get('inv')
                # Add usage to the list of usages of the corresponding station
                self.station_usage[station].append({
                    'agent': agent,
                    'at_station': at_station,
                    'init_charge': init_charge,
                    'end_charge': end_time,
                    'inv': inv
                })

        # Sort list of usages of every station
        for station in self.station_usage.keys():
            self.station_usage[station].sort(key=lambda x: x.get('at_station'))
        self.joint_plan['station_usage'] = self.station_usage
        self.flag_invalid_usage()

    def get_station_places(self, station_name):
        for station in self.config_dic.get('stations'):
            if station.get('name') == station_name:
                return station.get("places")

    def flag_invalid_usage(self):
        for station in self.joint_plan.get('station_usage').keys():
            usage_list = self.joint_plan.get('station_usage').get(station)
            for current_agent in usage_list:
                c = 0
                logger.critical(f"\nagent is {current_agent}")
                # Compare usage against all other usages which are not itself and are not invalid
                for other_agent in [x for x in usage_list if x.get('agent') != current_agent.get('agent')
                                                             and x.get('inv') is None]:
                    logger.critical(f"other agent is {other_agent}")
                    if other_agent.get('init_charge') < current_agent.get('init_charge') < other_agent.get(
                        'end_charge'):
                        c += 1
                        logger.critical("increasing counter")

                if c >= self.get_station_places(station):
                    # current_agent's usage is invalid
                    logger.critical(f'INVALID {current_agent}')
                    current_agent['inv'] = 'INV'
                    # To mark it as invalid:
                    #   Go to current_agent's plan, look for the appropriate charge action and flag it
                    agent = current_agent.get('agent')
                    agent_plan = self.joint_plan.get('individual').get(agent)
                    for entry in agent_plan.entries:
                        action = entry.action
                        if action.get('type') == 'CHARGE':
                            if action.get('statistics').get('init_charge') == current_agent.get('init_charge'):
                                action['inv'] = 'INV'

    # Checks stopping criteria of Best Response algorithm
    def stop(self):

        stop_by_loop = False

        # if we are detection loops
        if LOOP_DETECTION:
            # list to store a boolean indicating if an agent is repeating plans
            loops_in_agents = []
            for agent in self.agents:
                loops_in_agents.append(self.check_loop(agent))
                logger.debug("\n")

            # if all agents are repeating plans, stop_by_loop is True
            stop_by_loop = all(loops_in_agents)

            if stop_by_loop:
                logger.debug("All agents have a loop in their list of plans. Stop by LOOP.")

        stop = True

        # if no agent changed their plan, stop will be True
        for transport in self.joint_plan.get('no_change').keys():
            stop = stop and self.joint_plan.get('no_change').get(transport)

        if stop:
            logger.debug("All agents have kept the same plan. Stop by CONVERGENCE")

        return stop or stop_by_loop

    def create_initial_plans(self):
        for a in self.agents:
            agent_id = a.get('id')
            logger.info(f"Agent \'{agent_id}\''s turn")
            logger.info("-------------------------------------------------------------------------")
            logger.info(f"Creating first plan for agent {agent_id}")
            planner = self.create_planner(a)
            planner.run()
            new_plan = planner.plan
            self.check_update_joint_plan(agent_id, None, new_plan)

    def feasible_joint_plan(self):
        logger.debug(f"Creating an initial feasible plan")
        # Initial list with all customers
        customers = list(self.joint_plan.get("table_of_goals").keys())
        # Number of customers each agent will initially pick up
        customers_per_agent = math.ceil(len(customers) / len(self.agents))

        for agent in self.agents:
            logger.info(f"Creating initial plan for agent {agent.get('id')}")

            # Get actions
            dic_file = open(ACTIONS_FILE, "r")
            actions_dic = json.load(dic_file)
            agent_actions = actions_dic.get(agent.get('id'))

            pick_up_actions = agent_actions.get("PICK-UP")
            move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

            move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
            charge_actions = agent_actions.get("CHARGE")

            actions = []
            goals = []
            completed_goals = []
            if len(customers) >= customers_per_agent:
                # Assign their customers
                goals = random.sample(customers, k=customers_per_agent)
                # TODO hardcoded to repartir 1 2 3
                # goals.append(customers[0])
                # customers.pop(0)
                customers = [c for c in customers if c not in goals]
            else:
                goals = customers.copy()

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
            # Create plan with agent action list
            initial_plan = Plan(actions, -1, completed_goals)
            utility = self.evaluate_plan(initial_plan, initial_plan=True)
            initial_plan.utility = utility

            logger.info(f"Agent {agent.get('id')} initial plan:")
            logger.info(initial_plan.to_string_plan())

            # Update joint plan
            self.check_update_joint_plan(agent.get('id'), None, initial_plan)
            self.joint_plan["no_change"][agent.get('id')] = False

    def propose_plan(self, a):
        agent_id = a.get('id')
        logger.info("\n")
        logger.info(f"Agent \'{agent_id}\''s turn")
        logger.info("-------------------------------------------------------------------------")
        # Get plan from previous round
        prev_plan = self.get_individual_plan(a)
        # if previous plan is None (or Empty), indicates the agent could not find a plan in the previous round
        if prev_plan is None:
            logger.info(f"Agent {agent_id} has no previous plan")
        else:
            # Get previous plan utility
            prev_utility = prev_plan.utility
            # Calculate updated utility w.r.t. other agent's plans
            updated_utility = self.evaluate_plan(prev_plan)
            if prev_utility != updated_utility:
                logger.warning(f"Agent {agent_id} had its plan utility reduced "
                               f"from {prev_utility:.4f} to {updated_utility:.4f}")
                # NEW if the utility of the plan had changed, update it in the joint plan
                prev_plan.utility = updated_utility
                self.joint_plan["individual"][agent_id].utility = updated_utility

            else:
                logger.info(f"The utility of agent's {agent_id} plan has not changed")

            # if CONSIDER_PREV_PLAN:
            #     if self.best_prev_plan[agent_id][1] is not None and prev_plan.equals(self.best_prev_plan[agent_id][1]) \
            #         and updated_utility != self.best_prev_plan[agent_id][0]:
            #         logger.critical(
            #             f"The previous best plan had its utility updated. {self.best_prev_plan[agent_id][0]} -> {updated_utility}")
            #         self.best_prev_plan[agent_id] = (updated_utility, copy.deepcopy(prev_plan))
            #
            #     elif updated_utility > self.best_prev_plan[agent_id][0]:
            #         logger.critical(
            #             f"The previous best plan of the agent has changed. {self.best_prev_plan[agent_id][0]} < {updated_utility}")
            #         self.best_prev_plan[agent_id] = (updated_utility, copy.deepcopy(prev_plan))

        # Propose new plan as best response to joint plan
        logger.info("Searching for new plan proposal...")
        planner = self.create_planner(a)
        planner.run()
        new_plan = planner.plan

        # # If the new plan has lower utility than the best previous plan, propose the best previous plan again
        # if CONSIDER_PREV_PLAN and new_plan is not None:
        #     if new_plan.utility < self.best_prev_plan[agent_id][0]:
        #         logger.critical(f"The utility of the new plan {new_plan.utility} is lower than the updated utility of "
        #                         f"the best previous plan {self.best_prev_plan[agent_id][0]}. Proposing old plan instead.")
        #         new_plan = copy.deepcopy(self.best_prev_plan[agent_id][1])

        self.check_update_joint_plan(agent_id, prev_plan, new_plan)

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

                # Check for loops
                # self.check_loop(agent_id, new_plan)

                # Update list of plans
                if LOOP_DETECTION:
                    self.update_list_of_plans(agent_id, new_plan)

            # Case 3) Agent finds the same plan it had proposed before
            elif new_plan.equals(prev_plan):
                logger.critical("NO DEURIA ENTRAR ACÍ")
                logger.info(
                    f"Agent {agent_id} could not find a better plan (it found the same one than in the previous round)")
                self.update_joint_plan(agent_id, new_plan)
                self.joint_plan["no_change"][agent_id] = True

    # Keeps an updated list of the last 3 plans
    def update_list_of_plans(self, agent, new_plan):

        self.list_of_plans[agent].append(copy.deepcopy(new_plan))

        if len(self.list_of_plans[agent]) > 6:
            self.list_of_plans[agent].pop(0)

    def check_loop(self, agent):

        detections = 0
        agent_id = agent.get('id')
        # Check for loops in the Table of Goals
        for i in range(len(self.list_of_plans[agent_id])):
            for j in range(i + 1, len(self.list_of_plans[agent_id])):
                if self.list_of_plans[agent_id][i].equals(self.list_of_plans[agent_id][j]):
                    logger.critical(f'Detected loop in agent {agent_id} plans in indexes {i} and {j}')
                    detections += 1
                    plan1 = self.list_of_plans[agent_id][i]
                    plan2 = self.list_of_plans[agent_id][j]
                    # logger.info(f'Index {i}, plan {plan1.to_string_plan()}')
                    # logger.info(f'Index {j}, plan {plan2.to_string_plan()}')

        if detections > 0:
            logger.critical(f"Agent {agent_id} has {detections} pairs of equal plans in the list of previous plans")
            return True
        return False

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
        logger.debug(self.joint_plan.get("joint").print_plan())

        logger.debug("\n")
        logger.debug("Table of goals:")
        for customer in self.joint_plan.get('table_of_goals').keys():
            logger.debug(f"{customer:20s} : {self.joint_plan.get('table_of_goals').get(customer)}")

        logger.debug("\n")
        logger.debug("Station usage:")
        for station in self.joint_plan.get('station_usage').keys():
            if len(self.joint_plan.get('station_usage').get(station)) == 0:
                logger.debug(f"{station:20s} : []")
            else:
                logger.debug(f"{station:20s} : [")
                for usage in self.joint_plan.get('station_usage').get(station):
                    if usage.get('inv') is None:
                        logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
                                     f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}")
                    else:
                        logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
                                     f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, "
                                     f"{usage.get('inv')}")
                logger.debug("] \n")

        logger.debug("\n")
        logger.debug("No change in plan:")
        for agent in self.joint_plan.get('no_change').keys():
            logger.debug(f"{agent:20s} : {self.joint_plan.get('no_change').get(agent)}")

        logger.debug("#########################################################################")

    def run(self):
        # Read dictionary data
        self.initialize()
        # Create players
        self.create_agents()

        # Assign random order
        # random.shuffle(self.agents)
        # logger.debug("ATTENTION, NOT RANDOMIZING ORDER")
        logger.warning("ATTENTION, RANDOMIZING ORDER")
        logger.debug(f"Agent order {self.agents}")

        # Initialize data structure
        self.init_joint_plan()

        if INITIAL_JOINT_PLAN:
            self.feasible_joint_plan()
            self.print_game_state()

        game_turn = 0
        i = 0
        while not self.stop() and game_turn < 1000:  # 1000
            i += 1
            game_turn += 1
            logger.info("*************************************************************************")
            logger.info(f"\t\t\t\t\t\t\tBest Response turn {game_turn}")
            logger.info("*************************************************************************")
            # First turn of the game, agents propose their initial plan
            if game_turn == 1 and not INITIAL_JOINT_PLAN:
                self.create_initial_plans()
            # In the following turns, the agents may have one of this two:
            # 1) A previous plan
            # 2) An empty plan, because it can't do any action that increases its utility
            if game_turn > 1:
                for a in self.agents:
                    self.propose_plan(a)
            self.print_game_state()

        logger.info("END OF GAME")


if __name__ == '__main__':
    br = BestResponse()
    start = time.time()
    br.run()
    # br.obtain_best_plans()
    end = time.time()
    logger.debug(f'\tBRPS process time: {end - start}')
