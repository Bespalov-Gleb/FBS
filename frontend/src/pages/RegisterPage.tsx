import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Box,
  Card,
  CardContent,
  TextField,
  Button,
  Typography,
  Alert,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import { setCredentials } from '../store/authSlice';
import { authApi } from '../api/auth';
import type { RootState } from '../store';

function extractErrorMessage(err: unknown): string {
  if (!err || typeof err !== 'object') return 'Ошибка регистрации';
  const ax = err as { response?: { data?: { detail?: unknown }; status?: number }; message?: string };
  if (ax.response?.data?.detail !== undefined) {
    const d = ax.response.data.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      const first = d[0];
      if (typeof first === 'string') return first;
      if (first && typeof first === 'object' && 'msg' in first) return String((first as { msg: string }).msg);
    }
  }
  if (ax.response?.status === 0 || !ax.response) {
    return 'Не удалось подключиться к серверу. Проверьте, что backend запущен на http://localhost:8000';
  }
  if (ax.response?.status && ax.response.status >= 500) return 'Ошибка сервера. Попробуйте позже';
  return ax.message || 'Ошибка регистрации';
}

const schema = z
  .object({
    email: z.string().email('Некорректный email'),
    password: z.string().min(6, 'Минимум 6 символов'),
    confirm_password: z.string().min(1, 'Подтвердите пароль'),
    full_name: z.string().min(1, 'Введите имя'),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: 'Пароли не совпадают',
    path: ['confirm_password'],
  });

type FormData = z.infer<typeof schema>;

export default function RegisterPage() {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const accessToken = useSelector((state: RootState) => state.auth.accessToken);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (accessToken) {
      navigate('/assembly', { replace: true });
    }
  }, [accessToken, navigate]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '', confirm_password: '', full_name: '' },
  });

  const onSubmit = async (data: FormData) => {
    setError(null);
    try {
      const tokens = await authApi.register({
        email: data.email,
        password: data.password,
        full_name: data.full_name,
      });
      dispatch(setCredentials(tokens));
      navigate('/assembly', { replace: true });
    } catch (err: unknown) {
      const msg = extractErrorMessage(err);
      setError(msg);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
      }}
    >
      <Card sx={{ width: 400, maxWidth: '90%' }}>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h5" component="h1" gutterBottom align="center" fontWeight={600}>
            FBS.tools
          </Typography>
          <Typography variant="h6" gutterBottom align="center" color="text.secondary">
            Регистрация
          </Typography>
          <Box component="form" onSubmit={handleSubmit(onSubmit)} sx={{ mt: 2 }}>
            <TextField
              {...register('full_name')}
              label="Имя"
              fullWidth
              margin="normal"
              error={!!errors.full_name}
              helperText={errors.full_name?.message}
              autoComplete="name"
            />
            <TextField
              {...register('email')}
              label="Email"
              type="email"
              fullWidth
              margin="normal"
              error={!!errors.email}
              helperText={errors.email?.message}
              autoComplete="email"
            />
            <TextField
              {...register('password')}
              label="Пароль"
              type="password"
              fullWidth
              margin="normal"
              error={!!errors.password}
              helperText={errors.password?.message}
              autoComplete="new-password"
            />
            <TextField
              {...register('confirm_password')}
              label="Подтверждение пароля"
              type="password"
              fullWidth
              margin="normal"
              error={!!errors.confirm_password}
              helperText={errors.confirm_password?.message}
              autoComplete="new-password"
            />
            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={isSubmitting}
              sx={{ mt: 2 }}
            >
              Зарегистрироваться
            </Button>
          </Box>
          <Typography variant="body2" align="center" sx={{ mt: 2 }}>
            Уже есть аккаунт?{' '}
            <Link to="/login" style={{ color: 'inherit', fontWeight: 500 }}>
              Войти
            </Link>
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
