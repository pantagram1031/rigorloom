# HWP document adapter

HWP/HWPX assembly is intentionally maintained in the separate public
[hwp-master](https://github.com/pantagram1031/hwp-master) repository.

Clone it beside this repository or set `HWP_MASTER_ROOT`:

```sh
git clone https://github.com/pantagram1031/hwp-master.git ../hwp-master
export HWP_MASTER_ROOT="$(cd ../hwp-master && pwd)"
```

Stage playbooks use `<HWP_MASTER_ROOT>/scripts/...` placeholders. Any other
document backend may be substituted if it implements inspect, assemble, tidy,
measure, and proof-render operations described by the v0.6 contract.
