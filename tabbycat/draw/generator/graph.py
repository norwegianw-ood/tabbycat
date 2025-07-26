from collections import OrderedDict
from typing import Optional, TYPE_CHECKING

import munkres
import networkx as nx

from ..types import DebateSide

if TYPE_CHECKING:
    from participants.models import Team


def sign(n: int) -> int:
    """Sign function for integers, -1, 0, or 1"""
    try:
        return n // abs(n)
    except ZeroDivisionError:
        return 0


class GraphGeneratorMixin:
    def avoid_conflicts(self, pairings):
        """Graph optimisation avoids conflicts, so method is extraneous."""
        pass

    def assignment_cost(self, t1, t2, size, flags, team_flags, bracket=None) -> Optional[int]:
        if t1 is t2:  # Same team
            return

        penalty = 0
        if self.options["avoid_history"]:
            seen = t1.seen(t2)
            if seen:
                flags.append(f'history|{seen}')
            penalty += seen * self.options["history_penalty"]
        if self.options["avoid_institution"] and t1.same_institution(t2):
            flags.append('inst')
            penalty += self.options["institution_penalty"]

        # Add penalty of a side imbalance
        if self.options["side_allocations"] == "balance" and self.options["side_penalty"] > 0:
            t1_affs, t1_negs = t1.side_history
            t2_affs, t2_negs = t2.side_history

            if self.options["max_times_on_one_side"] > 0:
                if max(t1_affs, t1_negs, t2_affs, t1_negs) > self.options["max_times_on_one_side"]:
                    return

            # Only declare an imbalance if both sides have been on the same side more often
            # Affs are positive, negs are negative. If teams have opposite signs, negative imbalance
            # gets reduced to 0. Equalities have no restriction on the side to be allocated so
            # cancel as well. neg*neg -> pos
            imbalance = max(0, sign(t1_affs - t1_negs) * sign(t2_affs - t2_negs))

            # Get median imbalance between the two as a coefficient for the penalty to apply
            # This would prefer an imbalance of (+5 - +1) becoming (+4 - +2) rather than
            # (+5 - +4) becoming (+4 - +5), in a severe case.
            magnitude = (abs(t1_affs - t1_negs) + abs(t2_affs - t2_negs)) // 2

            if imbalance and magnitude:
                flags.append(f'side_imb|{magnitude}')

            penalty += imbalance * magnitude * self.options["side_penalty"]

        return penalty

    def get_n_teams(self, teams: list['Team']) -> int:
        return len(teams)

    def generate_pairings(self, brackets):
        """Creates an undirected weighted graph for each bracket and gets the minimum weight matching"""
        from .pairing import Pairing
        pairings = OrderedDict()
        i = 0
        for j, (points, teams) in enumerate(brackets.items()):
            pairings[points] = []
            graph = nx.Graph()
            n_teams = self.get_n_teams(teams)
            for k, t1 in enumerate(teams):
                for t2 in teams[k+1:]:
                    flags = []
                    team_flags = {t: [] for t in [t1, t2]}
                    penalty = self.assignment_cost(t1, t2, n_teams, flags, team_flags, j)
                    if penalty is not None:
                        graph.add_edge(t1, t2, weight=penalty, flags=flags, team_flags=team_flags)

            # nx.nx_pydot.write_dot(graph, sys.stdout)
            for pairing in sorted(nx.min_weight_matching(graph), key=lambda p: self.room_rank_ordering(p)):
                i += 1
                edge = graph.get_edge_data(*pairing)
                pairings[points].append(Pairing(teams=pairing, bracket=points, room_rank=i, flags=edge['flags'], team_flags=edge['team_flags']))

        return pairings

    def room_rank_ordering(self, p):
        return min([t.subrank for t in p if t.subrank is not None], default=0)


class GraphAllocatedSidesMixin(GraphGeneratorMixin):
    """Use Hungarian algorithm rather than Bloom.

    This is possible as assigning the sides creates a bipartite graph rather than
    a more complete graph."""

    def assignment_cost(self, t1, t2, size, flags, team_flags):
        penalty = super().assignment_cost(t1, t2, size, flags, team_flags)
        if penalty is None:
            return munkres.DISALLOWED
        return penalty

    def generate_pairings(self, brackets):
        from .pairing import Pairing
        pairings = OrderedDict()
        i = 0
        for points, pool in brackets.items():
            pairings[points] = []
            n_teams = len(pool[DebateSide.AFF]) + len(pool[DebateSide.NEG])
            matrix = [[self.assignment_cost(aff, neg, n_teams, [], {}) for neg in pool[DebateSide.NEG]] for aff in pool[DebateSide.AFF]]

            for i_aff, i_neg in munkres.Munkres().compute(matrix):
                i += 1
                pairings[points].append(Pairing(teams=[pool[DebateSide.AFF][i_aff], pool[DebateSide.NEG][i_neg]], bracket=points, room_rank=i))

        return pairings
