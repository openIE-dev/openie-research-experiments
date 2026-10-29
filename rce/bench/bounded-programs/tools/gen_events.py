"""Deterministic event stream for accounts.rce: N events, seeded LCG."""
import sys
def events(n, seed=12345):
    x = seed
    def r(m):
        nonlocal x
        x = (x * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        return (x >> 33) % m
    out = []
    for i in range(n):
        if i < 256:
            out.append(f"Open(id: {i})"); continue
        k = r(100)
        if k < 40:
            out.append(f"Deposit(id: {r(300)}, cents: {1 + r(20000)})")
        elif k < 95:
            out.append(f"Transfer(src: {r(256)}, dst: {r(256)}, cents: {1 + r(5000)})")
        elif k < 98:
            out.append(f"Fee(cents: {1 + r(50)})")
        else:
            out.append(f"Open(id: {r(300)})")
    return out
if __name__ == "__main__":
    for e in events(int(sys.argv[1])): print(e)
