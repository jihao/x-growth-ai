import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { Helmet, history, Link, useModel } from '@umijs/max';
import { Alert, App } from 'antd';
import React, { startTransition, useState } from 'react';
import { Footer } from '@/components';
import { login } from '@/services/ant-design-pro/api';
import Settings from '../../../../config/defaultSettings';

const Login: React.FC = () => {
  const [error, setError] = useState<string | null>(null);
  const { initialState, setInitialState } = useModel('@@initialState');
  const { message } = App.useApp();

  const fetchUserInfo = async () => {
    const userInfo = await initialState?.fetchUserInfo?.();
    if (userInfo) {
      startTransition(() => {
        setInitialState((state) => ({
          ...state,
          currentUser: userInfo,
        }));
      });
    }
  };

  const safeRedirect = () => {
    const redirect = new URL(window.location.href).searchParams.get('redirect');
    if (!redirect?.startsWith('/') || redirect.startsWith('//')) return '/xgrowth/home';
    return redirect;
  };

  const handleSubmit = async (values: API.LoginParams) => {
    setError(null);
    try {
      const result = await login(values);
      if (result.status === 'ok') {
        message.success('登录成功');
        await fetchUserInfo();
        history.replace(safeRedirect());
        return;
      }
      setError('用户名或密码错误');
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : '登录失败');
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f7fb', display: 'flex', flexDirection: 'column' }}>
      <Helmet>
        <title>登录 - {Settings.title}</title>
      </Helmet>
      <div style={{ flex: 1, padding: '56px 16px' }}>
        <LoginForm
          logo={<img alt="logo" src="/logo.svg" />}
          title="X-Growth AI"
          subTitle="交易研究工作台"
          initialValues={{ username: 'admin', password: 'admin123' }}
          submitter={{ searchConfig: { submitText: '登录' } }}
          onFinish={async (values) => {
            await handleSubmit(values as API.LoginParams);
          }}
        >
          {error && <Alert style={{ marginBottom: 24 }} message={error} type="error" showIcon />}
          <Alert
            style={{ marginBottom: 24 }}
            message="默认管理员：admin / admin123，首次登录后请在用户管理中修改密码。"
            type="info"
            showIcon
          />
          <ProFormText
            name="username"
            fieldProps={{ size: 'large', prefix: <UserOutlined /> }}
            placeholder="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          />
          <ProFormText.Password
            name="password"
            fieldProps={{ size: 'large', prefix: <LockOutlined /> }}
            placeholder="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          />
          <div style={{ textAlign: 'right' }}>
            <Link to="/user/register">注册新账户</Link>
          </div>
        </LoginForm>
      </div>
      <Footer />
    </div>
  );
};

export default Login;
