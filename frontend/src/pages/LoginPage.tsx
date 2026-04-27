import { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
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
import type { RootState } from '../store';
import { authApi } from '../api/auth';

const schema = z.object({
  email: z.string().email('Некорректный email'),
  password: z.string().min(6, 'Минимум 6 символов'),
});

type FormData = z.infer<typeof schema>;

export default function LoginPage() {
  const devAuthBypass = import.meta.env.VITE_DEV_AUTH_BYPASS === '1';
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useDispatch();
  const accessToken = useSelector((state: RootState) => state.auth.accessToken);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (devAuthBypass || accessToken) {
      const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? '/assembly';
      navigate(from, { replace: true });
    }
  }, [devAuthBypass, accessToken, location.state, navigate]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = async (data: FormData) => {
    setError(null);
    try {
      const tokens = await authApi.login(data);
      dispatch(setCredentials(tokens));
      const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? '/assembly';
      navigate(from, { replace: true });
    } catch (err: unknown) {
      let msg = 'Ошибка входа';
      if (err && typeof err === 'object' && 'response' in err) {
        const ax = err as { response?: { data?: { detail?: unknown } } };
        const d = ax.response?.data?.detail;
        if (typeof d === 'string') msg = d;
        else if (Array.isArray(d) && d[0] && typeof d[0] === 'object' && 'msg' in d[0]) {
          msg = String((d[0] as { msg: string }).msg);
        }
      }
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
            FBS-upakovka
          </Typography>
          <Typography variant="h6" gutterBottom align="center" color="text.secondary">
            Вход
          </Typography>
          <Box component="form" onSubmit={handleSubmit(onSubmit)} sx={{ mt: 2 }}>
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
              autoComplete="current-password"
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
              Войти
            </Button>
          </Box>
          <Typography variant="body2" align="center" sx={{ mt: 2 }}>
            Нет аккаунта?{' '}
            <Link to="/register" style={{ color: 'inherit', fontWeight: 500 }}>
              Зарегистрироваться
            </Link>
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
