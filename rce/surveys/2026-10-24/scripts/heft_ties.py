import sys
sys.path.insert(0, sys.argv[1])
from core import schedule, makespan
succ = {'root': ('t1','t2','t3','t4'), 't1': ('sink',), 't2': ('sink',), 't3': ('sink',), 't4': ('sink',)}
agents = ['cpu0', 'gpu0', 'gpu1'] if sys.argv[2] == 'list' else {'cpu0', 'gpu0', 'gpu1'}
compcost = lambda job, agent: 1.0
commcost = lambda ni, nj, a, b: 0.0 if a == b else 0.5
orders, jobson = schedule(succ, agents, compcost, commcost)
print(makespan(orders), sorted(jobson.items()))
