export default [
  {
    path: '/user',
    layout: false,
    routes: [
      {
        path: '/user/login',
        name: 'login',
        component: './user/login',
      },
      {
        path: '/user/register',
        name: 'register',
        component: './user/register',
      },
      {
        path: '/user',
        redirect: '/user/login',
      },
    ],
  },
  {
    path: '/',
    redirect: '/xgrowth/home',
  },
  {
    path: '/xgrowth/home',
    name: '首页',
    icon: 'home',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/screen',
    name: '选股看板',
    icon: 'stock',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/stock',
    name: '个股分析',
    icon: 'lineChart',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/stock/:code',
    name: '个股分析',
    hideInMenu: true,
    component: './xgrowth',
  },
  {
    path: '/xgrowth/strategy',
    name: '策略验证',
    icon: 'barChart',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/concentration',
    name: '集中度趋势',
    icon: 'pieChart',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/reports',
    name: '日报区域',
    icon: 'fileText',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/history',
    name: '历史 Markdown',
    icon: 'history',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/learning',
    name: '学习区域',
    icon: 'book',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/data',
    name: '数据区域',
    icon: 'database',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/tools',
    name: '工具中心',
    icon: 'tool',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/watchlist',
    name: '观察池',
    icon: 'eye',
    component: './xgrowth',
  },
  {
    path: '/xgrowth/users',
    name: '用户管理',
    icon: 'team',
    access: 'canAdmin',
    component: './xgrowth',
  },
  {
    path: '*',
    component: './exception/404',
  },
];
