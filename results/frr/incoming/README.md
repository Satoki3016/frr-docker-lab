# 新規結果の受け取り先

`frr_measure.sh` / `run_all_scenarios.sh` / `run_experiment.sh` / `physical2_frr_measure_all.sh` を直接実行した場合、既定でこの下の `<タグ>/` に保存します。

`radwin_experiment.sh` は目的が分かっているため、最初から `radwin/dynamic/` または `radwin/comparison/` に保存します。

計測が完了した結果は、[分類ルール](../README.md) に従って用途別フォルダへ移動してください。`FRR_RESULTS_ROOT` を指定すれば、直接実行でも目的の保存先を選べます。

```bash
sudo env LAB_MODE=c2 ROUTE_MODE=wcmp \
  FRR_RESULTS_ROOT="$PWD/results/frr/radwin/comparison" \
  bash scripts/frr_measure.sh 60 normal 20260919_compare_wcmp_01
```
