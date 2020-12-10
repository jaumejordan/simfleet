class Plan:
    def __init__(self, actions, value, completed_goals):
        self.entries = []
        self.table_of_goals = {}
        self.utility = value
        self.fill_entries(actions.copy())
        self.fill_goals(completed_goals.copy())

    def fill_entries(self, actions):
        init_time = 0.0
        for a in actions:
            duration = a.get('statistics').get('time')
            e = PlanEntry(init_time, a, duration)
            self.add(e)
            init_time += duration

    def fill_goals(self, completed_goals):
        for tup in completed_goals:
            self.table_of_goals[tup[0]] = tup[1]

    def add(self, entry):
        self.entries.append(entry)

    def sort_plan(self):
        self.entries.sort(key=lambda x: x.init_time)

    def get_actions(self):
        return [entry.action for entry in self.entries]

    def print_plan(self):
        print(f'{"init time":10s}  ||  {"action":50s}  ||  {"end time":10s}  ||  {"duration":10s}')
        print("-------------------------------------------------------------------------------------------------\n")
        for e in self.entries:
            e.print_simple()
        end_time = self.entries[-1].init_time + self.entries[-1].duration
        print(f'{end_time:10.4f}  ::  {"****** END-OF-PLAN *****":50s}  ::  {"":10s}')

    def to_string_plan(self):
        s = "\n"
        s += f'{"init time":10s}  ||  {"action":50s}  ||  {"end time":10s}  ||  {"duration":10s}\n'
        s += "-------------------------------------------------------------------------------------------------\n"
        for e in self.entries:
            s += e.to_string_simple()
        end_time = self.entries[-1].init_time + self.entries[-1].duration
        s += f'{end_time:10.4f}  ::  {"****** END-OF-PLAN *****":50s}\n'
        return s

    def equals(self, o):
        # equal = self.utility == o.utility
        equal = (len(self.entries) == len(o.entries))
        for i in range(len(self.entries)):
            equal = equal and self.entries[i].equals(o.entries[i])
        return equal


def equals_actions(a1, a2):
    agent1 = a1.get('agent')
    agent2 = a2.get('agent')

    attributes1 = a1.get('attributes')

    if agent1 != agent2:
        return False
    else:
        type1 = a1.get('type')
        type2 = a2.get('type')

        if type1 != type2:
            return False
        else:
            attributes1 = a1.get('attributes')
            attributes2 = a2.get('attributes')


class PlanEntry:
    def __init__(self, init_time, action, duration):
        self.init_time = init_time
        self.action = action
        self.duration = duration
        self.end_time = init_time + duration

    def print(self):
        print(f'{self.init_time:.4f}  ::  {self.action}  ::  {self.end_time:.4f}  ||  {self.duration:.4f}')

    def print_simple(self):
        action_string = ""
        if self.action.get('type') in ['PICK-UP', 'MOVE-TO-DEST']:
            action_string += str(
                (self.action.get('agent'), self.action.get('type'), self.action.get('attributes').get('customer_id')))
        else:
            action_string += str(
                (self.action.get('agent'), self.action.get('type'), self.action.get('attributes').get('station_id')))

        print(f'{self.init_time:10.4f}  ::  {action_string:50s}  ::  {self.end_time:10.4f}  ||  {self.duration:10.4f}')

    def to_string_simple(self):
        action_string = ""
        if self.action.get('type') in ['PICK-UP', 'MOVE-TO-DEST']:
            action_string += str(
                (self.action.get('agent'), self.action.get('type'), self.action.get('attributes').get('customer_id')))
        else:
            action_string += str(
                (self.action.get('agent'), self.action.get('type'), self.action.get('attributes').get('station_id')))

        return f'{self.init_time:10.4f}  ::  {action_string:50s}  ::  {self.end_time:10.4f}  ||  {self.duration:10.4f}\n'

    def equals(self, o):
        return self.init_time == o.init_time and self.action == o.action and \
               self.duration == o.duration and self.end_time == o.end_time


class JointPlan:
    def __init__(self, entries):
        self.entries = entries

    def print_plan(self):
        s = "\n"
        s += f'{"init time":10s}  ||  {"action":50s}  ||  {"end time":10s}  ||  {"duration":10s}\n'
        s += "-------------------------------------------------------------------------------------------------\n"
        for e in self.entries:
            s += e.to_string_simple()
        end_time = self.entries[-1].init_time + self.entries[-1].duration
        s += f'{end_time:10.4f}  ::  {"****** END-OF-PLAN *****":50s}\n'
        return s


class Action:
    def __init__(self, agent, type, attributes, statistics):
        self.agent = agent
        self.type = type
        self.attributes = attributes
        self.statistics = statistics
