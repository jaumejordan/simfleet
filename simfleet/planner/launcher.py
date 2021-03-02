from best_response import BestResponse
from database import Database
from planner import Planner

db = Database()

br = BestResponse(database=db)
br.run()


def test_planner():
    agent_id = 'taxi1'
    agent_pos = agent_max_autonomy = None
    for transport in db.config_dic.get('transports'):
        if transport.get('name') == agent_id:
            agent_pos = transport.get('position')
            agent_max_autonomy = transport.get('autonomy')
            agent_autonomy = transport.get('current_autonomy')
    agent_goals = ['customer1', 'customer2', 'customer3', 'customer4']
    planner = Planner(database=db,
                      agent_id=agent_id,
                      agent_pos=agent_pos,
                      agent_max_autonomy=agent_max_autonomy,
                      agent_autonomy=agent_autonomy,
                      agent_goals=agent_goals)
    planner.run()
