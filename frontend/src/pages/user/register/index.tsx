import { LockOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { Helmet, history, Link } from '@umijs/max';
import { Alert, App } from 'antd';
import React, { useState } from 'react';
import { Footer } from '@/components';
import { register } from '@/services/ant-design-pro/api';
import Settings from '../../../../config/defaultSettings';

const Register: React.FC = () => {
  const [error, setError] = useState<string | null>(null);
  const { message } = App.useApp();

  const handleSubmit = async (values: API.RegisterParams) => {
    setError(null);
    try {
      await register(values);
      message.success('注册成功，请登录');
      history.replace('/user/login');
    } catch (registerError) {
      setError(registerError instanceof Error ? registerError.message : '注册失败');
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f7fb', display: 'flex', flexDirection: 'column' }}>
      <Helmet>
        <title>注册 - {Settings.title}</title>
      </Helmet>
      <div style={{ flex: 1, padding: '56px 16px' }}>
        <LoginForm
          logo={<img alt="logo" src="/logo.svg" />}
          title="X-Growth AI"
          subTitle="创建本地 SQLite 账户"
          submitter={{ searchConfig: { submitText: '注册' } }}
          onFinish={async (values) => {
            await handleSubmit(values as API.RegisterParams);
          }}
        >
          {error && <Alert style={{ marginBottom: 24 }} message={error} type="error" showIcon />}
          <ProFormText
            name="username"
            fieldProps={{ size: 'large', prefix: <UserOutlined /> }}
            placeholder="用户名：3-32 位字母、数字、下划线或短横线"
            rules={[{ required: true, message: '请输入用户名' }]}
          />
          <ProFormText
            name="display_name"
            fieldProps={{ size: 'large', prefix: <TeamOutlined /> }}
            placeholder="显示名称"
          />
          <ProFormText.Password
            name="password"
            fieldProps={{ size: 'large', prefix: <LockOutlined /> }}
            placeholder="密码至少 6 位"
            rules={[{ required: true, message: '请输入密码' }]}
          />
          <div style={{ textAlign: 'right' }}>
            <Link to="/user/login">已有账户，去登录</Link>
          </div>
        </LoginForm>
      </div>
      <Footer />
    </div>
  );
};

export default Register;
