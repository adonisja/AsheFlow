ROLE_BOOST = {
    "driver": 0.70,
    "trainer": 0.50,
    "walker": 0.30
}

MUTUAL_BONUS = {
    "bidirectional": 0.10,
    "tridirectional": 0.20
}

CONSECUTIVE_PENALTY = 0.05
CAP = 0.85

MIN_TRAINERS_PER_TRUCK = 2
MIN_WALKERS_PER_TRUCK = 3

# Number of dispatch days a mandatory task can be carried as debt before the
# TrainingRecord is flagged for manager escalation.
DEBT_ESCALATION_THRESHOLD = 3