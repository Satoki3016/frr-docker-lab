# FRR実験結果の案内

**現在のRADWIN実験は `radwin/`、従来の優先度比較は `qos/` にあります。**
2026-09-18に、直下の44ディレクトリを目的別に整理しました。実験フォルダ名と、内部の生データ・ログ・図・PDFは保持しています。

## 最初に見る結果

| 用途 | 保存先 | 記録の扱い |
|---|---|---|
| 動的制御と3クラスの同時計測 | [20260918_success_dynamic_integrated](radwin/dynamic/20260918_success_dynamic_integrated/) | 終了コード0、3クラス各64フロー、制御91サンプル・適用失敗0 |
| 動的制御単体の図・ECMP比較図 | [20260918_success_dynamic_control](radwin/dynamic/20260918_success_dynamic_control/) | 図4ファイル。制御単体の元CSVはこのフォルダにはない |
| 無線2.16Gで静的WCMP | [20260918_wcmp_ref](radwin/comparison/20260918_wcmp_ref/) | 9月18日報告で使用した比較データ |
| 無線2.16GでECMP | [20260918_ecmp_ref2](radwin/comparison/20260918_ecmp_ref2/) | `_ecmp_ref` の欠測後の再計測 |
| 無線0.9Gで静的WCMP / ECMP | [WCMP](radwin/comparison/20260918_wcmp/) / [ECMP](radwin/comparison/20260918_ecmp_nopolice/) | 容量の異なる条件の比較 |
| 物理C2でSP有効 / 無効 | [SP有効](qos/c2/20260721_c2_sp_enabled/) / [SP無効](qos/c2/20260721_c2_sp_uniform/) | 発表・QoS評価で使用したデータと日英の図 |

終了コードやファイル名の `success` は、実験仮説の成立を保証しません。
9月18日のECMP/WCMP比較データは、当時の障害注入によるHTB消失の影響が報告されており、failure系の復旧後区間（t≧43秒）の扱いに注意が必要です。詳しくは [当時の報告](../../docs/進捗報告_動的制御_20260918.pdf) を参照してください。

## 分類

```text
results/frr/
├── radwin/                  現在の無線・有線ハイブリッド実験
│   ├── dynamic/             動的制御・3クラスとの同時計測
│   ├── comparison/          ECMPと静的WCMPの比較
│   ├── validation/          起動確認・ストリーム数検討・再試行前のデータ
│   └── setup/               無線導入とMTU問題の記録
├── qos/                     従来のSP有効/無効の比較
│   ├── c2/                  独立3経路の物理実験
│   ├── c1/                  共有物理ファブリックの比較
│   └── veth/                仮想環境の比較
├── archive/                 旧条件・初期試行・由来の古い成果物
│   ├── 2026-06/             6月の13実験
│   ├── 2026-07/             7月の8実験（QoS比較として上に分けたものを除く）
│   ├── legacy/              旧「基本使わない」を内容ごと保管
│   └── legacy_figures/      元の直下PNGとfigures。由来を推定して統合しない
├── reports/                 直下にあった報告PDF 3件
├── tools/                   専用の解析・図・報告書生成スクリプト
├── incoming/                従来の計測スクリプトを直接実行した新規結果
├── plot_frr.py              共通グラフ生成の入口（従来の位置を維持）
├── catalog.csv              今回移動した全63項目の旧パス→新パス対応表
└── README.md                この案内
```

`validation/` に保存するのは検討過程です。失敗だけを意味しません。
たとえば `20260918_smoke_run` は欠測あり、`20260918_smoke_run2` は保存された検査結果がOKです。
`archive/` も削除候補を意味せず、過去条件を再確認するために保持しています。

## 今後の保存ルール

1. **実験1回につき1フォルダ**。名前は `YYYYMMDD_結果_目的_条件_連番` です (2026-09-25 統一)。例: `20260925_success_unplug_wcmp_01`。
   結果は `radwin_experiment.sh` が自動で付けます。実行中は `running`、終了時に `success` / `fail` に付け替えます。
   `running` のまま残ったフォルダは、途中で強制終了された実験です。
   解析では結果語を省いた名前 (`20260925_unplug_wcmp_01`) でも指定できます。
2. **保存先を実験の目的で決める**。動的制御は `radwin/dynamic/`、静的経路比較は `radwin/comparison/`。新しいラッパーは自動で振り分けます。
3. **合否はログで決める**。計測前に成功と決めず、`status.txt` (`result=`) / `validation.txt` に基づいて付けます。
   `success` は「計測として正常に完了した (欠測・制御の適用失敗なし)」の意味で、実験仮説の成立は意味しません。
   2026-09-25 以前の結果語なしのフォルダは名前を変えずに残しています。
4. **同じ実験番号を再利用しない**。結果語が違っても同じ番号は使いません。条件変更・再測定は連番を増やします。
5. **生データとその図を同じ実験内に保存する**。シナリオは `frr_normal/` など、図は `ja/` / `en/` など既存形式を維持します。
6. **直下に実験フォルダや図を追加しない**。従来コマンドの新規出力は `incoming/` に入り、用途が確定した段階で適切な分類へ移動します。

```bash
# 動的制御・同時計測 → radwin/dynamic/<タグ>/
sudo bash scripts/radwin_experiment.sh run 120 20260919_antenna_wcmp_01

# 静的比較 → radwin/comparison/<タグ>/
sudo bash scripts/radwin_experiment.sh measure 60 all 20260919_compare_ecmp_01 ecmp

# 実行せず、保存先とコマンドを確認
bash scripts/radwin_experiment.sh --plan run 120 20260919_antenna_wcmp_01
```

## グラフ生成・古いパスの読み替え

共通プロッターは分類フォルダを再帰的に探索します。従来のタグ名だけの指定も有効です。
同名タグが複数ある場合は分類からの相対パスを指定します。

```bash
python3 results/frr/plot_frr.py --list
python3 results/frr/plot_frr.py --base 20260918_success_dynamic_integrated --cr-mbps 2160
python3 results/frr/plot_frr.py --base qos/c2/20260721_c2_sp_enabled --cr-mbps 9000

# 専用解析スクリプトはtools/に集約
python3 results/frr/tools/plot_qos_steady.py --help
```

過去PDFや実行ログに書かれた旧パスは、[catalog.csv](catalog.csv) で読み替えてください。
たとえば旧 `results/frr/20260721_c2_sp_enabled/` は `results/frr/qos/c2/20260721_c2_sp_enabled/` です。
保存済みの `commands.log`、`source_sha256.txt`、PDFなどは実行時の記録として書き換えていません。

共通プロッター、現行の専用解析、報告生成、比較用スクリプトの参照先は更新しています。
各旧実験フォルダ内にある当時のスクリプトのコピーは、原資料として保持しています。通常の再描画には直下の共通プロッターを使ってください。

移動前の全1,750ファイルのSHA-256は `.organization_manifest.json` に記録しています。
今回の参照先更新対象である現行Pythonスクリプトを除き、ファイル内容が一致することを確認しています。
実験の操作手順は [RADWIN実験ガイド](../../docs/radwin_experiment.md) を参照してください。
