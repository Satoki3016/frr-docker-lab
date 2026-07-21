# veth / C1 / C2 × SP有効/無効 比較サマリ

DiffServ-TE（HTB SP+WRR）の Strict Priority 設計則を、3つの異なる物理構成で
検証した6条件（veth/C1/C2 × SP有効/無効）の比較成果物をまとめたフォルダ。

## 中身

| ファイル | 内容 |
|---|---|
| `veth_c1_c2_comparison_table.md` | 6条件の統合数値表（スループット・損失率・OWD・障害断絶時間）。全数値は実ログからの算出値 |
| `fig_af41_loss_ablation.png/pdf` | **主図**: AF41損失率の対数軸グループ棒グラフ。SP有効(0.001%台) vs SP無効(34%)の約4桁差を示す |
| `fig_class_throughput_ablation.png/pdf` | 補助図: クラス別スループット2パネル（SP有効=AF41独占 / SP無効=quantum比4:2:1分配） |
| `fig_throughput_timeseries{,_failure,_reroute}.png/pdf` | **SP有効**スループット60秒時系列(クラス別3段、veth vs C2、理論値破線)。normal/failure/rerouteの3シナリオ。failure/rerouteは障害区間(t=20-40s)を網掛け表示 |
| `fig_owd_sim_vs_real.png/pdf` | **SP有効**片道遅延OWDの60秒時系列(sim-to-real図, normal)。スループットは一致するが遅延には物理差(AF41のみ)が出ることを示す |
| `fig_throughput_timeseries_uniform{,_failure,_reroute}.png/pdf` | **SP無効**スループット60秒時系列。normal/failure/rerouteの3シナリオ。理論値=quantumフルシェア(5.14/2.57/1.29G) |
| `fig_owd_timeseries_uniform.png/pdf` | **SP無効**OWD 60秒時系列(normal)。SP有効比でAF41が0.16ms→約14msに悪化(優先保護喪失)、AF42/43は改善(帯域増でキュー滞留減) |

| `fig_scenario_comparison_shared.png/pdf` | **スループット同一軸重ね図**: 3クラス(3段)、各パネルにSP有効/無効を同一スケールで重ねる。色=シナリオ・線種=SPモード。AF41で実線(SP有効8G)が破線(SP無効5.3G)より上=SP保護効果が直読できる |
| `fig_owd_comparison_combined.png/pdf` | **遅延OWD左右分割図**(線形軸): 3クラス(行)×SP有効/無効(列)×3シナリオ(線)。各セル単一モードで値域が狭いため線形軸で数値を直読可能。1秒中央値 |
| `fig_owd_comparison_shared.png/pdf` | **遅延OWD同一軸重ね図**(対数軸): 上記スループット同一軸図の遅延版。AF41で破線(SP無効14ms)が実線(SP有効0.16ms)より上=SPは低遅延も与える。AF42/43は逆(SP有効が高遅延)。障害中は欠測で線が途切れる。1秒中央値で集計 |
| `fig_scenario_comparison_combined.png/pdf` | **左右分割図**: 3クラス(行)×SP有効/無効(列)×3シナリオ(線)。y軸は列ごと独立スケールで各モードの挙動を潰さず表示 |
| `fig_scenario_comparison{,_uniform}.png/pdf` | **シナリオ重ね図(モード別)**: 実機C2の3シナリオ(normal/failure/reroute)を1枚に重ねたスループット時系列 |

### 障害シナリオの見方（failure vs reroute）
- **failure(迂回なし・赤破線)**: 障害区間t=20-40sの間、全クラスが0に落ちたまま（約17秒断）
- **failure_reroute(自動迂回・青一点鎖線)**: t=22付近で一瞬0に落ちるがOSPF-SR迂回で数秒以内に回復（約1-2秒断）
- **`fig_scenario_comparison`** が3シナリオを1枚に重ねた図で、OSPF-SR自動迂回の効果(20秒断→数秒断)を直接対比できる。配色はplot_frr.py準拠(正常=緑実線/迂回なし=赤破線/迂回=青一点鎖線)。
- `fig_throughput_timeseries_{failure,reroute}` はシナリオごとにveth vs C2を比較する詳細版(sim-to-real確認用)

**図の環境は veth（シミュレーション基準）と C2（実機代表・完全独立3経路）の2つに絞っている。**
C1（共有トランク）はC2とほぼ同一結果のため図からは省略。C1のデータは
`veth_c1_c2_comparison_table.md` と `results/frr/20260716_sp_enabled`/`_sp_uniform` に保全済み。

### sim-to-realの要点（fig_owd_sim_vs_real）
- **スループット・損失率はHTB(ソフトウェア)が支配** → veth/C2で一致 = SP設計則の普遍性の証拠
- **遅延(OWD)は物理層が支配** → 実機で増える = 物理実在性の証拠
- ただし物理差(~0.07ms)が見えるのは**AF41(優先クラス、キュー待ちほぼ無し)のみ**。
  AF42/AF43はHTBキュー待ち(225ms/900ms)が支配的で物理差が埋もれる。
  veth AF41=88μs / C2 AF41=162μs（約2倍）、AF42/AF43は両環境ほぼ同一。
| `plot_sp_ablation.py` | 上記2図の生成スクリプト。実験データは `../frr/` を参照、図は本フォルダに出力。データ更新時は再実行するだけ |

## 実験条件（全6条件で完全統一、2026-07-21）

- **CR帯域: 9G**（全環境統一）／**送信レート: 8G/クラス**（全環境統一）
- 比較変数はSP有無と物理構成(veth/C1/C2)の2つのみ

## 元データの所在（`results/frr/` 配下、すべてCR=9G）

| 条件 | フォルダ |
|---|---|
| veth SP有効 | `20260721_veth9G_sp_enabled` |
| veth SP無効 | `20260721_veth9G_sp_uniform` |
| C1 SP有効 | `20260716_sp_enabled` |
| C1 SP無効 | `20260716_sp_uniform` |
| C2 SP有効 | `20260721_c2_sp_enabled` |
| C2 SP無効 | `20260721_c2_sp_uniform` |

※旧veth 10Gデータは `20260703_experiment_veth10G_OLD` / `20260721_veth_sp_uniform_10G_OLD` に保全。

## 再生成方法

```bash
python3 results/20260721_veth_c1_c2_summary/plot_sp_ablation.py
```

## 主張（新規性①: HTB SP設計則）

3つの全く異なる物理構成（仮想リンクのみ / 1トランク共有 / 完全独立3経路）すべてで、
SP有効時はAF41がほぼ無損失、SP無効時はquantum比4:2:1の機械的分配になる同一現象が
再現された。SP設計則が経路構成に依存しない普遍的な結論であることの実証データ。

2026-07-21更新: CR帯域を全環境9Gに統一して再計測したことで、SP無効時のAF41損失は
3環境すべてで34%に一致（旧版はvethのみ10Gで27%という交絡があった）。これで送信・
リンク条件が完全に揃い、環境間の差はSP有無のみに帰属できる状態になった。
