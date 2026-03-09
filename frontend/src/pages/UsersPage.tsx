import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Chip,
  Snackbar,
  Alert,
  Tooltip,
  CircularProgress,
} from '@mui/material';
import Add from '@mui/icons-material/Add';
import Edit from '@mui/icons-material/Edit';
import Block from '@mui/icons-material/Block';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import RefreshIcon from '@mui/icons-material/Refresh';
import { usersApi, type UserCreate, type UserUpdate } from '../api/users';
import AddUserModal from '../features/users/AddUserModal';
import EditUserModal from '../features/users/EditUserModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorAlert from '../components/common/ErrorAlert';

export default function UsersPage() {
  const queryClient = useQueryClient();
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [deactivateConfirm, setDeactivateConfirm] = useState<{ id: number; name: string } | null>(null);
  const [snackbar, setSnackbar] = useState<{ message: string; severity: 'success' | 'error' } | null>(null);

  const { data: users = [], isLoading, error, refetch } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  });

  const { data: inviteCodeData, isLoading: inviteLoading } = useQuery({
    queryKey: ['my-invite-code'],
    queryFn: () => usersApi.getMyInviteCode(),
  });

  const regenerateMutation = useMutation({
    mutationFn: () => usersApi.regenerateMyInviteCode(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-invite-code'] });
      setSnackbar({ message: 'Код обновлён', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка обновления кода', severity: 'error' }),
  });

  const handleCopyInviteCode = () => {
    if (inviteCodeData?.code) {
      navigator.clipboard.writeText(inviteCodeData.code).then(() => {
        setSnackbar({ message: 'Код скопирован', severity: 'success' });
      });
    }
  };

  const createMutation = useMutation({
    mutationFn: (payload: UserCreate) => usersApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setAddModalOpen(false);
      setSnackbar({ message: 'Пользователь добавлен', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка добавления', severity: 'error' }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UserUpdate }) =>
      usersApi.update(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setEditId(null);
      setSnackbar({ message: 'Изменения сохранены', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка сохранения', severity: 'error' }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => usersApi.deactivate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setDeactivateConfirm(null);
      setSnackbar({ message: 'Пользователь деактивирован', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка', severity: 'error' }),
  });

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h4" fontWeight={600}>
          Пользователи
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Администрирование / Пользователи
        </Typography>
      </Box>
      {/* ── Инвайт-код администратора ── */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ mb: 0.5 }}>
            Ваш инвайт-код для регистрации упаковщиков
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {inviteLoading ? (
              <CircularProgress size={16} />
            ) : (
              <Typography variant="body1" fontFamily="monospace" fontWeight={700} fontSize="1.1rem" letterSpacing={2}>
                {inviteCodeData?.code ?? '—'}
              </Typography>
            )}
            {inviteCodeData?.code && (
              <Tooltip title="Скопировать">
                <IconButton size="small" onClick={handleCopyInviteCode}>
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Box>
          <Typography variant="caption" color="text.secondary">
            Упаковщик вводит этот код при регистрации. Код постоянный и многоразовый.
          </Typography>
        </Box>
        <Tooltip title="Сгенерировать новый код (старый перестанет работать)">
          <span>
            <Button
              variant="outlined"
              size="small"
              startIcon={regenerateMutation.isPending ? <CircularProgress size={14} /> : <RefreshIcon />}
              onClick={() => regenerateMutation.mutate()}
              disabled={regenerateMutation.isPending}
            >
              Обновить код
            </Button>
          </span>
        </Tooltip>
      </Paper>

      <Button
        variant="contained"
        startIcon={<Add />}
        onClick={() => setAddModalOpen(true)}
        sx={{ mb: 2 }}
      >
        Добавить
      </Button>

      {error && (
        <ErrorAlert
          message={error instanceof Error ? error.message : 'Ошибка загрузки'}
          onRetry={() => refetch()}
        />
      )}

      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Email</TableCell>
                <TableCell>Имя</TableCell>
                <TableCell>Роль</TableCell>
                <TableCell>Статус</TableCell>
                <TableCell align="right">Действия</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>{u.full_name}</TableCell>
                  <TableCell>{u.role === 'admin' ? 'Админ' : 'Упаковщик'}</TableCell>
                  <TableCell>
                    <Chip
                      label={u.is_active ? 'Активен' : 'Неактивен'}
                      size="small"
                      color={u.is_active ? 'success' : 'default'}
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => setEditId(u.id)}>
                      <Edit />
                    </IconButton>
                    {u.is_active && (
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setDeactivateConfirm({ id: u.id, name: u.full_name })}
                      >
                        <Block />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {addModalOpen && (
        <AddUserModal
          onClose={() => setAddModalOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
          isSubmitting={createMutation.isPending}
        />
      )}

      {editId && (
        <EditUserModal
          userId={editId}
          onClose={() => setEditId(null)}
          onSubmit={(payload) => updateMutation.mutate({ id: editId, payload })}
          isSubmitting={updateMutation.isPending}
        />
      )}

      <ConfirmDialog
        open={!!deactivateConfirm}
        title="Деактивировать пользователя?"
        message={`Вы уверены, что хотите деактивировать "${deactivateConfirm?.name}"?`}
        confirmLabel="Деактивировать"
        confirmColor="error"
        onConfirm={() => deactivateConfirm && deactivateMutation.mutate(deactivateConfirm.id)}
        onCancel={() => setDeactivateConfirm(null)}
      />

      <Snackbar
        open={!!snackbar}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSnackbar(null)} severity={snackbar?.severity ?? 'success'}>
          {snackbar?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
