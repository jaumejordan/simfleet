from loguru import logger
import numpy as np


def get_electric_grid(station):
    return 1

# electric_grids = {
#     1: [station1, ...]
# }

# station_usage = {
#     station1: [usage1, ...]
# }

# usage1 = {
#     agent: taxi1,
#     station: station1,
#     at_station: 5.50,
#     init_charge: 5.50,
#     end_charge: 11.20,
#     inv: None/INV
#     }

def check_charge_congestion(u1, original_cost, station_usage):
    # Compare if current usage overlaps with any other usage
    congestion_time = 0
    u1_grid = get_electric_grid(u1.get('station'))
    # Compare against charges in stations of the same grid
    same_grid_stations = [x for x in station_usage if get_electric_grid(x.get('station')) == u1_grid]
    # Save individual congestion percentages
    overlaps = np.ndarray([0])
    for u2 in same_grid_stations:
        if u2.get('inv') is None and u2.get('agent') != u1.get('agent'):  # you can't overlap with yourself
            ov = overlap(u1, u2)
            if ov > 0:
                if ov == 1:
                    congestion_time = u2.get('end_charge') - u1.get('init_charge')
                if ov == 2:
                    congestion_time = u1.get('end_charge') - u2.get('init_charge')
                if ov == 3:
                    congestion_time = u1.get('end_charge') - u1.get('init_charge')
                if ov == 4:
                    congestion_time = u2.get('end_charge') - u2.get('init_charge')

                congestion_percentage = congestion_time / (u1.get('end_charge') - u1.get('init_charge'))
                overlaps = np.append(overlaps, [congestion_percentage])

    # Capacitat de la xarxa abans de congestionar-se
    if len(overlaps) > u1_grid.capacitat:
        mean_congestion = overlaps.mean()
        return charge_congestion_function(u1_grid, original_cost, mean_congestion)


# increment en percentatges
def charge_congestion_function(grid, cost, mean_congestion):
    # TODO use different values according to different grids
    if mean_congestion <= 0.3:
        new_cost = cost + mean_congestion * cost
    elif 0.3 < mean_congestion <= 0.7:
        new_cost = 2*cost
    else:
        new_cost = 5*cost
    return new_cost


def check_congestion_network(u1, station_usage, electric_grids):
    for grid in electric_grids.keys():
        same_grid_stations = electric_grids.get(grid)
        # Get a list of every charge occurring in the grid
        same_grid_charges = []
        for station in same_grid_stations:
            same_grid_charges += station_usage.get(station)
            for i in range(len(same_grid_charges)):
                u1 = same_grid_charges[i]
                for j in range(i + 1, len(same_grid_charges)):
                    u2 = same_grid_charges[j]


def overlap(u1, u2):
    # u1 starts before u2 finishes
    case1 = u2.get('init_charge') < u1.get('init_charge') < u2.get('end_charge') \
            and u1.get('init_charge') < u2.get('end_charge') < u1.get('end_charge')

    # u2 starts before u1 finishes
    case2 = u1.get('init_charge') < u2.get('init_charge') < u1.get('end_charge') \
            and u2.get('init_charge') < u1.get('end_charge') < u2.get('end_charge')

    # u1 inside u2
    case3 = u1.get('init_charge') > u2.get('init_charge') and u1.get('end_charge') < u2.get('end_charge')
    # u2 inside u1
    case4 = u2.get('init_charge') > u1.get('init_charge') and u2.get('end_charge') < u1.get('end_charge')

    res = []

    if case1:
        logger.debug(f"Usage nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}] starts before "
                     f"nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] finishes")
        res.append(1)
    if case2:
        logger.debug(f"Usage nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] starts before "
                     f"nº1[{u1.get('init_charge')}, {u1.get('end_charge')}] finishes")
        res.append(2)
    if case3:
        logger.debug(f"Usage nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}] is contained in "
                     f"nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}]")
        res.append(3)
    if case4:
        logger.debug(f"Usage nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] is contained in "
                     f"nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}]")
        res.append(4)
    return res
    # detects cases 1 to 3?
    # a = u1.get('end_charge') > u2.get('init_charge') and u1.get('init_charge') < u2.get('end_charge')
