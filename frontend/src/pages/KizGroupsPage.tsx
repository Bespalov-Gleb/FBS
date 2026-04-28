import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  InputLabel,
  ListItemText,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  CircularProgress,
} from '@mui/material';
import FileUpload from '@mui/icons-material/FileUpload';
import Save from '@mui/icons-material/Save';
import Download from '@mui/icons-material/Download';
import UploadFile from '@mui/icons-material/UploadFile';
import DeleteSweep from '@mui/icons-material/DeleteSweep';
import DeleteForever from '@mui/icons-material/DeleteForever';
import { marketplacesApi } from '../api/marketplaces';
import { kizGroupsApi, type KizGroup, type KizGroupPayload } from '../api/kizGroups';
import { useSelector } from 'react-redux';
import type { RootState } from '../store';

type Notice = { text: string; severity: 'success' | 'error' };

type GroupFormState = {
  name: string;
  color: string;
  size: string;
  cut_type: string;
  parser_markers: string;
  marketplace_ids: number[];
};

const defaultForm: GroupFormState = {
  name: '',
  color: '',
  size: '',
  cut_type: '',
  parser_markers: '',
  marketplace_ids: [],
};

function parseMarkers(raw: string): Record<string, unknown> | null {
  const text = raw.trim();
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null;
  } catch {
    throw new Error('Поле "Параметры парсера" должно быть валидным JSON.');
  }
}

export default function KizGroupsPage() {
  const user = useSelector((state: RootState) => state.auth.user);
  const queryClient = useQueryClient();
  const [form, setForm] = useState<GroupFormState>(defaultForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [uploadingGroupId, setUploadingGroupId] = useState<number | null>(null);

  const { data: groups = [] } = useQuery({
    queryKey: ['kiz-groups'],
    queryFn: () => kizGroupsApi.list(),
  });
  const { data: marketplaces = [] } = useQuery({
    queryKey: ['marketplaces'],
    queryFn: () => marketplacesApi.list(),
  });
  const { data: products = [] } = useQuery({
    queryKey: ['kiz-products', search],
    queryFn: () => kizGroupsApi.listProducts(search),
  });

  const groupOptions = useMemo(
    () => groups.map((g) => ({ id: g.id, name: g.name })),
    [groups],
  );

  const saveGroupMutation = useMutation({
    mutationFn: async () => {
      const payload: KizGroupPayload = {
        name: form.name.trim(),
        color: form.color.trim() || null,
        size: form.size.trim() || null,
        cut_type: form.cut_type.trim() || null,
        parser_markers: parseMarkers(form.parser_markers),
        marketplace_ids: form.marketplace_ids,
      };
      if (!payload.name) throw new Error('Введите название группы.');
      if (editingId) return kizGroupsApi.update(editingId, payload);
      return kizGroupsApi.create(payload);
    },
    onSuccess: () => {
      setNotice({ text: editingId ? 'Группа обновлена.' : 'Группа создана.', severity: 'success' });
      setForm(defaultForm);
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ['kiz-groups'] });
    },
    onError: (error: unknown) => {
      setNotice({
        text: error instanceof Error ? error.message : 'Не удалось сохранить группу.',
        severity: 'error',
      });
    },
  });

  const uploadPdfMutation = useMutation({
    mutationFn: async (args: { groupId: number; files: File[] }) => kizGroupsApi.uploadPdf(args.groupId, args.files),
    onMutate: (args) => {
      setUploadingGroupId(args.groupId);
    },
    onSuccess: (res) => {
      setNotice({
        text: `Импорт завершен. Добавлено: ${res.imported}, дубликаты: ${res.duplicates}, ошибки: ${res.errors}.`,
        severity: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['kiz-groups'] });
    },
    onError: (error: unknown) => {
      setNotice({ text: error instanceof Error ? error.message : 'Ошибка загрузки PDF.', severity: 'error' });
    },
    onSettled: () => {
      setUploadingGroupId(null);
    },
  });

  const updateProductGroupMutation = useMutation({
    mutationFn: async (payload: { marketplace_id: number; article: string; size: string; group_id: number }) =>
      kizGroupsApi.upsertProductMapping(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kiz-products', search] });
    },
    onError: () => setNotice({ text: 'Не удалось сохранить соответствие товара.', severity: 'error' }),
  });

  const clearGroupItemsMutation = useMutation({
    mutationFn: async (groupId: number) => kizGroupsApi.clearGroupItems(groupId),
    onSuccess: (res) => {
      setNotice({
        text: `Содержимое группы очищено. Удалено КИЗ: ${res.deleted_pool}, ошибок: ${res.deleted_errors}.`,
        severity: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['kiz-groups'] });
    },
    onError: (error: unknown) => {
      setNotice({ text: error instanceof Error ? error.message : 'Ошибка очистки группы.', severity: 'error' });
    },
  });

  const deleteGroupMutation = useMutation({
    mutationFn: async (groupId: number) => kizGroupsApi.deleteGroup(groupId),
    onSuccess: () => {
      setNotice({ text: 'Группа удалена.', severity: 'success' });
      if (editingId) {
        setEditingId(null);
        setForm(defaultForm);
      }
      queryClient.invalidateQueries({ queryKey: ['kiz-groups'] });
    },
    onError: (error: unknown) => {
      setNotice({ text: error instanceof Error ? error.message : 'Ошибка удаления группы.', severity: 'error' });
    },
  });

  const importMappingsMutation = useMutation({
    mutationFn: async () => {
      if (!importFile) throw new Error('Выберите файл импорта.');
      return kizGroupsApi.importProductsFile(importFile);
    },
    onSuccess: (res) => {
      setNotice({
        text: `Импорт соответствий завершен. Создано: ${res.created}, обновлено: ${res.updated}, пропущено: ${res.skipped}.`,
        severity: 'success',
      });
      setImportFile(null);
      queryClient.invalidateQueries({ queryKey: ['kiz-products', search] });
    },
    onError: (error: unknown) => {
      setNotice({ text: error instanceof Error ? error.message : 'Ошибка импорта соответствий.', severity: 'error' });
    },
  });

  const fillFormFromGroup = (group: KizGroup) => {
    setEditingId(group.id);
    setForm({
      name: group.name,
      color: group.color ?? '',
      size: group.size ?? '',
      cut_type: group.cut_type ?? '',
      parser_markers: group.parser_markers ? JSON.stringify(group.parser_markers, null, 2) : '',
      marketplace_ids: group.marketplace_ids,
    });
  };

  const handleUploadPdfs = (groupId: number, files: FileList | null) => {
    if (!files || files.length === 0) return;
    uploadPdfMutation.mutate({ groupId, files: Array.from(files) });
  };

  const handleClearGroupItems = (group: KizGroup) => {
    const ok = window.confirm(
      `Очистить содержимое группы "${group.name}"? Будут удалены все загруженные КИЗ и ошибки парсинга.`,
    );
    if (!ok) return;
    clearGroupItemsMutation.mutate(group.id);
  };

  const handleDeleteGroup = (group: KizGroup) => {
    const ok = window.confirm(`Удалить группу "${group.name}"? Это действие нельзя отменить.`);
    if (!ok) return;
    deleteGroupMutation.mutate(group.id);
  };

  if (user?.role !== 'admin') {
    return <Alert severity="warning">Раздел доступен только администратору.</Alert>;
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="h4" fontWeight={600}>КИЗ-группы</Typography>
      <Typography variant="body2" color="text.secondary">
        Администратор настраивает группы, загружает PDF с КИЗ и связывает товары с группами.
      </Typography>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>
            {editingId ? 'Редактирование группы' : 'Новая группа'}
          </Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
            <TextField
              label="Название"
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
              fullWidth
            />
            <TextField
              label="Цвет"
              value={form.color}
              onChange={(e) => setForm((prev) => ({ ...prev, color: e.target.value }))}
              fullWidth
            />
            <TextField
              label="Размер"
              value={form.size}
              onChange={(e) => setForm((prev) => ({ ...prev, size: e.target.value }))}
              fullWidth
            />
            <TextField
              label="Крой (A/B/В...)"
              value={form.cut_type}
              onChange={(e) => setForm((prev) => ({ ...prev, cut_type: e.target.value }))}
              fullWidth
            />
          </Stack>
          <Box sx={{ mt: 1.5 }}>
            <FormControl fullWidth>
              <InputLabel>Магазины группы</InputLabel>
              <Select
                multiple
                label="Магазины группы"
                value={form.marketplace_ids}
                onChange={(e) => setForm((prev) => ({ ...prev, marketplace_ids: e.target.value as number[] }))}
                renderValue={(selected) =>
                  marketplaces
                    .filter((m) => (selected as number[]).includes(m.id))
                    .map((m) => m.name)
                    .join(', ')
                }
              >
                {marketplaces.map((mp) => (
                  <MenuItem key={mp.id} value={mp.id}>
                    <ListItemText primary={mp.name} />
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
          <TextField
            sx={{ mt: 1.5 }}
            label="Параметры парсера (JSON, опционально)"
            multiline
            minRows={3}
            value={form.parser_markers}
            onChange={(e) => setForm((prev) => ({ ...prev, parser_markers: e.target.value }))}
            fullWidth
          />
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            <Button
              variant="contained"
              startIcon={<Save />}
              onClick={() => saveGroupMutation.mutate()}
              disabled={saveGroupMutation.isPending}
            >
              Сохранить группу
            </Button>
            {editingId && (
              <Button
                variant="outlined"
                onClick={() => {
                  setEditingId(null);
                  setForm(defaultForm);
                }}
              >
                Отменить редактирование
              </Button>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
            <Button startIcon={<Download />} onClick={() => kizGroupsApi.downloadReport('free')}>
              Остатки
            </Button>
            <Button startIcon={<Download />} onClick={() => kizGroupsApi.downloadReport('used')}>
              Использованные
            </Button>
            <Button startIcon={<Download />} onClick={() => kizGroupsApi.downloadReport('errors')}>
              Ошибки парсера
            </Button>
          </Stack>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Группа</TableCell>
                <TableCell>Магазины</TableCell>
                <TableCell>Остаток</TableCell>
                <TableCell>Использовано</TableCell>
                <TableCell>Ошибки</TableCell>
                <TableCell align="right">Действия</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {groups.map((g) => (
                <TableRow key={g.id}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={600}>{g.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {g.color || '—'} / {g.size || '—'} / {g.cut_type || '—'}
                    </Typography>
                    {uploadingGroupId === g.id && (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                        <CircularProgress size={14} />
                        <Typography variant="caption" color="text.secondary">
                          Парсинг PDF, подождите...
                        </Typography>
                      </Box>
                    )}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} flexWrap="wrap">
                      {g.marketplace_ids.map((mpId) => {
                        const mp = marketplaces.find((m) => m.id === mpId);
                        return <Chip key={mpId} size="small" label={mp?.name || `#${mpId}`} />;
                      })}
                    </Stack>
                  </TableCell>
                  <TableCell>{g.free_count}</TableCell>
                  <TableCell>{g.used_count}</TableCell>
                  <TableCell>{g.parser_errors_count}</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button size="small" onClick={() => fillFormFromGroup(g)}>Редактировать</Button>
                      <Button component="label" size="small" startIcon={<UploadFile />}>
                        PDF
                        <input
                          hidden
                          type="file"
                          multiple
                          accept=".pdf"
                          onChange={(e) => handleUploadPdfs(g.id, e.target.files)}
                        />
                      </Button>
                      <Button
                        size="small"
                        color="warning"
                        startIcon={<DeleteSweep />}
                        onClick={() => handleClearGroupItems(g)}
                        disabled={clearGroupItemsMutation.isPending || uploadingGroupId === g.id}
                      >
                        Очистить
                      </Button>
                      <Button
                        size="small"
                        color="error"
                        startIcon={<DeleteForever />}
                        onClick={() => handleDeleteGroup(g)}
                        disabled={deleteGroupMutation.isPending || uploadingGroupId === g.id}
                      >
                        Удалить
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Соответствие товаров и групп
          </Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 1 }}>
            <TextField
              label="Поиск по артикулу/названию"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              fullWidth
            />
            <Button startIcon={<Download />} onClick={() => kizGroupsApi.downloadProductsExport()}>
              Выгрузить файл товаров
            </Button>
            <Button component="label" startIcon={<FileUpload />}>
              Загрузить соответствия
              <input
                hidden
                type="file"
                accept=".xlsx,.csv"
                onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
              />
            </Button>
            <Button
              variant="contained"
              onClick={() => importMappingsMutation.mutate()}
              disabled={!importFile || importMappingsMutation.isPending}
            >
              Импорт
            </Button>
          </Stack>
          {importFile && (
            <Alert severity="info" sx={{ mb: 1 }}>
              Файл для импорта: {importFile.name}
            </Alert>
          )}
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Магазин</TableCell>
                <TableCell>Артикул</TableCell>
                <TableCell>Размер</TableCell>
                <TableCell>Товар</TableCell>
                <TableCell>Группа</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {products.map((row) => (
                <TableRow key={`${row.marketplace_id}-${row.article}-${row.size}`}>
                  <TableCell>{row.marketplace_name}</TableCell>
                  <TableCell>{row.article}</TableCell>
                  <TableCell>{row.size || '—'}</TableCell>
                  <TableCell>{row.product_name}</TableCell>
                  <TableCell sx={{ minWidth: 240 }}>
                    <Select
                      size="small"
                      value={row.group_id ?? ''}
                      displayEmpty
                      fullWidth
                      onChange={(e) =>
                        updateProductGroupMutation.mutate({
                          marketplace_id: row.marketplace_id,
                          article: row.article,
                          size: row.size ?? '',
                          group_id: Number(e.target.value),
                        })
                      }
                    >
                      <MenuItem value="" disabled>Выберите группу</MenuItem>
                      {groupOptions.map((g) => (
                        <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>
                      ))}
                    </Select>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Snackbar
        open={!!notice}
        autoHideDuration={4000}
        onClose={() => setNotice(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={notice?.severity ?? 'success'} onClose={() => setNotice(null)}>
          {notice?.text}
        </Alert>
      </Snackbar>
    </Box>
  );
}
