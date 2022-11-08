# Game-Theoretic-Deep-Reinforcement-Learning

This is the code of paper, named "Joint Task Offloading and Resource Optimization in NOMA-based Vehicular Edge Computing: A Game-Theoretic DRL Approach", and the proposed solution and comparison algorithms are implemented.

## File Structure

### Main Program
The main program of the repo is `Experiment/experiment.py`.

### Algorithms

- Multi-agent distributed distributional deep deterministic policy gradient (MAD4PG): `Experiment/run_mad4pg.py`
- Multi-agent deep deterministic policy gradient (MADDPG): `Experiment/run_maddpg.py`
- Distributed distributional deep deterministic policy gradient (D4PG): `Experiment/run_d4pg.py`
- Optimal resource allocation and task local processing only (ORL): `Experiment/run_optres_local.py`
- Optimal resource allocation and task migration only (ORM): `Experiment/run_optres_edge.py`

## Citing this paper 
```bibtex
@article{xu2022joint,
  title={Joint Task Offloading and Resource Optimization in NOMA-based Vehicular Edge Computing: A Game-Theoretic DRL Approach},
  author={Xu, Xincao and Liu, Kai and Dai, Penglin and Jin, Feiyu and Ren, Hualing and Zhan, Choujun and Guo, Songtao},
  journal={arXiv preprint arXiv:2209.12749},
  year={2022}
}
```
