"""Small static proof of the intended passive-equivalent transformation."""

import re
from examples.microrobot import tcad_passive_clamps as passive


def test_only_expected_open_branches_probes_and_low_clamps_change():
    prior = passive.SOURCE.read_text()
    deck = passive.build_deck()
    for name, (high, low, node) in passive.CLAMPS.items():
        assert re.search(r"^" + high + r" ", deck, re.M) is None
        assert re.search(r"^" + low + r" ", deck, re.M) is None
        assert f"Rfixed_{name} {node} 0 10k" in deck
    for port in passive.REMOVED_PORTS:
        assert f"i({port})" not in deck
        assert re.search(r"^" + port + r" ", deck, re.M) is None
    assert re.findall(r"^Bpv.*$", deck, re.M) == re.findall(r"^Bpv.*$", prior, re.M)
    # Reverse the bounded substitutions and recover the exact prior deck.
    restored = deck
    for name, (high, low, node) in passive.CLAMPS.items():
        oldlow = re.search(r"^" + low + r" .*$", prior, re.M).group()
        restored = restored.replace(f"Rfixed_{name} {node} 0 10k", oldlow)
    removed_prefixes = list(passive.REMOVED_PORTS) + [x[0] for x in passive.CLAMPS.values()]
    reduced_prior = "\n".join(
        line
        for line in prior.split("\n")
        if not any(line.startswith(prefix + " ") for prefix in removed_prefixes)
    )
    for port in passive.REMOVED_PORTS:
        reduced_prior = reduced_prior.replace(f"i({port}) ", "")
    assert restored == reduced_prior
