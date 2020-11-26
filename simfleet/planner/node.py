from loguru import logger


class Node:
    def __init__(self, parent=None):

        # If there is no parent, use default value for attributes
        if parent is None:
            self.parent = None
            # Agent attributes in the node
            #   current position
            self.agent_pos = None
            #   current autonomy
            self.agent_autonomy = None
            # Node planner-related attributes
            self.init_time = 0.0
            self.actions = []

            # Llista customers de l'agent + llista d'atesos
            # New: list with names of customers assigned to the agent
            self.agent_goals = []
            # List with names of already served customers
            self.completed_goals = []
            # Attributes for evaluation
            self.benefits = 0
            self.costs = 0

            # Llista customers atesos + Llista de customers per atendre

        # If there is parent, inherit attributes
        else:
            self.parent = parent
            self.agent_pos = parent.agent_pos[:]
            self.agent_autonomy = parent.agent_autonomy  # .copy()
            self.init_time = parent.end_time  # .copy()
            self.actions = parent.actions[:]  # .copy()
            # New
            self.agent_goals = parent.agent_goals[:]  # .copy()
            self.completed_goals = parent.completed_goals[:]  # .copy()
            self.benefits = parent.benefits
            self.costs = parent.costs

        # Independent values for every node
        #   own f-value
        self.value = None
        self.end_time = None
        # to store children node (if any)
        self.children = []

    def set_end_time(self):
        self.end_time = sum(a.get('statistics').get('time') for a in self.actions)

    # Given the list of completed goals, which contains tuples (customer_id, pick_up_time),
    # compiles a list of the served customers' ids.
    def already_served(self):
        res = []
        for tup in self.completed_goals:
            res.append(tup[0])
        return res

    def print_node(self):
        action_string = "\n"
        for a in self.actions:
            if a.get('type') in ['PICK-UP', 'MOVE-TO-DEST']:
                action_string += str((a.get('agent'), a.get('type'), a.get('attributes').get('customer_id'))) + ",\n"
            else:
                action_string += str((a.get('agent'), a.get('type'), a.get('attributes').get('station_id'))) + ",\n"

            # if its the last action, remove ", "
            if a == self.actions[-1]:
                action_string = action_string[:-2]
        logger.info(
            f'(\n\tagent position:\t{self.agent_pos}\n'
            f'\tagent autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[{action_string}]\n'
            f'\tinit time:\t{self.init_time:.4f}\n'
            f'\tend time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tagent goals:\t{self.agent_goals}\n'
            f'\tcompleted goals:\t{self.completed_goals}\n'
            f'\thas parent?:\t{self.parent is not None}\n'
            f'\thas children?:\t{len(self.children)}\t)'
        )

    def print_node_action_info(self):
        action_string = ""
        for a in self.actions:
            action_string += str(a) + "\n"
        logger.info(
            f'(\n\tagent_position:\t{self.agent_pos}\n'
            f'\tagent_autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[\n{action_string}]\n'
            f'\tinit_time:\t{self.init_time:.4f}\n'
            f'\tend_time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tagent goals:\t{self.agent_goals}\n'
            f'\tcompleted_goals:\t{self.completed_goals}\n'
            f'\thas parent?:\t{self.parent is not None}\n'
            f'\thas children?:\t{len(self.children)}\t)'
        )
