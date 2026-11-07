#!/usr/bin/env bash
# 重生主版紧凑范例：用真实管线(build_itinerary + plan_transit + render_compact)重新生成
# examples/ 下的 5 个主版 HTML，使 §01/§03 出现真实景点（而非「咖啡馆发呆」套话）。
# 用法：bash tools/regen_examples.sh
set -u
cd "$(dirname "$0")/.."
PY=python3

# 每行：outfile|title|build参数|transit_from|transit_to
EXAMPLES=(
"examples/example-wuhan-citywalk-2d.html|武汉城市漫步 2 天|--from 武汉 --to 武汉 --days 2 --people 2 --style leisure --season 秋|武汉|武汉"
"examples/example-harbin-sanya-5d.html|哈尔滨 - 三亚 5 天|--from 哈尔滨 --to 三亚 --days 5 --people 2 --style leisure --season 冬|哈尔滨|三亚"
"examples/example-changsha-hiking-weekend.html|长沙周末徒步 2 天|--from 长沙 --to 岳麓山 --days 2 --people 2 --style hiking --tag sunrise --season 秋|长沙|岳麓山"
"examples/example-hangzhou-xinjiang-drive.html|杭州 - 新疆自驾 8 天|--from 杭州 --to 新疆 --days 8 --people 2 --style roadtrip --season 夏|杭州|新疆"
"examples/example-yueyang-sunrise-reference.html|岳阳楼区·周末近郊日出爬山一页路书|--from 岳阳楼区 --to 岳阳楼区 --days 2 --people 1 --style hiking --tag sunrise --season 秋|岳阳楼区|岳阳楼区"
)

for ex in "${EXAMPLES[@]}"; do
  IFS='|' read -r out title bargs tfrm tto <<< "$ex"
  echo "── 生成 $out"
  $PY scripts/build_itinerary.py $bargs --json > _rp.json 2>_re.txt || { echo "  BUILD FAIL"; cat _re.txt; continue; }
  $PY scripts/plan_transit.py --from "$tfrm" --to "$tto" --json > _rt.json 2>>_re.txt || echo "  TRANSIT WARN"
  $PY scripts/render_compact.py --plan _rp.json --transit _rt.json --title "$title" --out "$out" 2>>_re.txt || { echo "  RENDER FAIL"; cat _re.txt; continue; }
  echo "  OK ($(wc -c < "$out") bytes)"
done

rm -f _rp.json _rt.json _re.txt
echo "完成。"
