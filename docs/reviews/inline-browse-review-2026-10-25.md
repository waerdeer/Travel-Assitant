# 酒店与美食原位展开

用户要求：浏览结果应在当前卡片下方展开，不能返回页面顶部。

本次前端修正：

- 删除 TravelPlan 顶部统一浏览面板，改为每个活动/住宿入口各自维护展开状态。
- 美食结果紧接对应活动按钮，住宿结果紧接对应住宿按钮，保留在当天卡片内部。
- 移除 PlaceBrowser 的 scrollIntoView；使用行内 region 与按钮 aria-expanded/aria-controls。
- 再点按钮收起，面板关闭按钮也只影响自身；多个地点可独立展开。
- 忙碌、会话或正式版本变化时清理展开状态；组件卸载继续中止旧浏览请求。窄容器网格可缩为单列。

验证：前端 lint/TypeScript/build 通过。主站 5173 的南京已完成行程只读浏览验证，不提交新规划、不修改正式行程：

1. 第二天颐和路美食展开前后 document scrollTop 均为 1355.5；面板是按钮紧邻后继，父元素 stop-detail，属于 DAY 02。真实候选和图片加载正常。
2. 第二天酒店展开前后 scrollTop 均为 2920.5；面板在 daily-stay 内，属于 DAY 02；已展开的美食保留。
3. 关闭酒店后只剩美食面板；再次点击收起特色美食后，面板数及 aria-expanded=true 按钮数均为 0。

截图：`inline-browse-food.png`、`inline-browse-hotels.png`。后端无改动，无提交或推送。
