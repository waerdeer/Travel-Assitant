import {
  MessageSquare,
  Search,
  Route,
  ShieldCheck,
  Check,
  Users,
} from "lucide-react";
export const stages = [
  {
    key: "understand",
    title: "理解你的旅行",
    detail: "提取目的地、日期与偏好",
    icon: MessageSquare,
  },
  {
    key: "research",
    title: "寻找真实线索",
    detail: "先检索活动，再按路线补充食宿",
    icon: Search,
  },
  {
    key: "draft_route",
    title: "先看路线草案",
    detail: "用有来源的主要活动勾勒每天方向",
    icon: Route,
  },
  {
    key: "review_options",
    title: "按需探索食宿",
    detail: "默认先完成行程，想看时再浏览",
    icon: Users,
  },
  {
    key: "plan",
    title: "编排每日行程",
    detail: "根据证据与约束生成计划",
    icon: Route,
  },
  {
    key: "validate",
    title: "检查，再完善",
    detail: "校验时间、预算与地点来源",
    icon: ShieldCheck,
  },
  {
    key: "deliver",
    title: "交付旅行计划",
    detail: "保存行程与执行记录",
    icon: Check,
  },
];
export const statusText: Record<string, string> = {
  completed: "校验通过",
  degraded: "部分数据缺失",
  awaiting_clarification: "等待补充",
  awaiting_choice: "等你选择",
  needs_revision: "仍需调整",
  failed: "执行未完成",
  blocked: "规划受阻",
  chat: "对话",
  planning: "规划中",
};
