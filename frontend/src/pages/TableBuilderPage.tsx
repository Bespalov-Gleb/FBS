import { useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  List,
  ListItem,
  ListItemText,
  Snackbar,
  Typography,
} from '@mui/material';
import TableView from '@mui/icons-material/TableView';
import DeleteSweep from '@mui/icons-material/DeleteSweep';
import UploadFile from '@mui/icons-material/UploadFile';
import { tableBuilderApi } from '../api/tableBuilder';

const ACCEPTED_EXTENSIONS = ['.xlsx', '.csv'];

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'table.xlsx';
  a.click();
  URL.revokeObjectURL(url);
}

export default function TableBuilderPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [inputKey, setInputKey] = useState(0);
  const [snackbar, setSnackbar] = useState<{ text: string; severity: 'success' | 'error' } | null>(null);

  const acceptedExtensionsLabel = useMemo(() => ACCEPTED_EXTENSIONS.join(', '), []);

  const buildMutation = useMutation({
    mutationFn: async () => tableBuilderApi.build(files),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
      setSnackbar({ text: 'Таблица успешно сформирована и скачана.', severity: 'success' });
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error
          ? error.message
          : 'Не удалось сформировать таблицу. Проверьте формат файлов и попробуйте снова.';
      setSnackbar({ text: message, severity: 'error' });
    },
  });

  const handleSelectFiles = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? []);
    if (selected.length === 0) return;
    setFiles(selected);
  };

  const handleClear = () => {
    setFiles([]);
    setInputKey((prev) => prev + 1);
  };

  const handleBuild = () => {
    if (files.length === 0) {
      setSnackbar({ text: 'Сначала загрузите хотя бы один файл.', severity: 'error' });
      return;
    }
    buildMutation.mutate();
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight={600} gutterBottom>
        Формирование таблицы
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Загрузите файлы Ozon/WB и сформируйте итоговую Excel-таблицу.
      </Typography>

      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Button component="label" variant="outlined" startIcon={<UploadFile />} sx={{ alignSelf: 'flex-start' }}>
              Загрузить файлы
              <input
                key={inputKey}
                hidden
                multiple
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(',')}
                onChange={handleSelectFiles}
              />
            </Button>

            <Typography variant="caption" color="text.secondary">
              Поддерживаются файлы: {acceptedExtensionsLabel}
            </Typography>

            {files.length > 0 ? (
              <List dense sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                {files.map((file) => (
                  <ListItem key={`${file.name}-${file.size}-${file.lastModified}`}>
                    <ListItemText primary={file.name} secondary={`${(file.size / 1024).toFixed(1)} KB`} />
                  </ListItem>
                ))}
              </List>
            ) : (
              <Alert severity="info">Файлы пока не выбраны.</Alert>
            )}

            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="contained"
                startIcon={<TableView />}
                onClick={handleBuild}
                disabled={buildMutation.isPending}
              >
                {buildMutation.isPending ? 'Собираю...' : 'Собрать таблицу'}
              </Button>
              <Button
                variant="outlined"
                color="inherit"
                startIcon={<DeleteSweep />}
                onClick={handleClear}
                disabled={files.length === 0 || buildMutation.isPending}
              >
                Очистить
              </Button>
            </Box>
          </Box>
        </CardContent>
      </Card>

      <Snackbar
        open={!!snackbar}
        autoHideDuration={3500}
        onClose={() => setSnackbar(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar?.severity ?? 'info'} onClose={() => setSnackbar(null)}>
          {snackbar?.text}
        </Alert>
      </Snackbar>
    </Box>
  );
}
