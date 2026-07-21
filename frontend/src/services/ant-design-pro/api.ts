// @ts-ignore
/* eslint-disable */
import { request } from '@umijs/max';

/** 获取当前的用户 GET /api/currentUser */
export async function currentUser(options?: { [key: string]: any }) {
  const payload = await request<{ user: API.AppUser | null }>('/api/auth/me', {
    method: 'GET',
    ...(options || {}),
  });
  if (!payload.user) {
    throw new Error('not authenticated');
  }
  return {
    data: toCurrentUser(payload.user),
  };
}

/** 退出登录接口 POST /api/login/outLogin */
export async function outLogin(options?: { [key: string]: any }) {
  return request<Record<string, any>>('/api/auth/logout', {
    method: 'POST',
    ...(options || {}),
  });
}

/** 登录接口 POST /api/login/account */
export async function login(body: API.LoginParams, options?: { [key: string]: any }) {
  const payload = await request<{ user: API.AppUser }>('/api/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    data: body,
    ...(options || {}),
  });
  return {
    status: 'ok',
    type: 'account',
    currentAuthority: payload.user.role,
  };
}

export async function register(body: API.RegisterParams, options?: { [key: string]: any }) {
  return request<API.AppUser>('/api/auth/register', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    data: body,
    ...(options || {}),
  });
}

function toCurrentUser(user: API.AppUser): API.CurrentUser {
  return {
    id: user.id,
    userid: String(user.id),
    name: user.display_name || user.username,
    username: user.username,
    access: user.role,
    role: user.role,
    status: user.status,
    title: user.role === 'admin' ? '管理员' : '普通用户',
    avatar: 'https://mdn.alipayobjects.com/huamei_7uahnr/afts/img/A*EX7zQK4d7rUAAAAAAAAAAAAADrJ8AQ/original',
  };
}

/** 此处后端没有提供注释 GET /api/notices */
export async function getNotices(options?: { [key: string]: any }) {
  return request<API.NoticeIconList>('/api/notices', {
    method: 'GET',
    ...(options || {}),
  });
}

/** 获取规则列表 GET /api/rule */
export async function rule(
  params: {
    // query
    /** 当前的页码 */
    current?: number;
    /** 页面的容量 */
    pageSize?: number;
  },
  options?: { [key: string]: any },
) {
  return request<API.RuleList>('/api/rule', {
    method: 'GET',
    params: {
      ...params,
    },
    ...(options || {}),
  });
}

/** 更新规则 PUT /api/rule */
export async function updateRule(options?: { [key: string]: any }) {
  return request<API.RuleListItem>('/api/rule', {
    method: 'POST',
    data: {
      method: 'update',
      ...(options || {}),
    },
  });
}

/** 新建规则 POST /api/rule */
export async function addRule(options?: { [key: string]: any }) {
  return request<API.RuleListItem>('/api/rule', {
    method: 'POST',
    data: {
      method: 'post',
      ...(options || {}),
    },
  });
}

/** 删除规则 DELETE /api/rule */
export async function removeRule(options?: { [key: string]: any }) {
  return request<Record<string, any>>('/api/rule', {
    method: 'POST',
    data: {
      method: 'delete',
      ...(options || {}),
    },
  });
}
