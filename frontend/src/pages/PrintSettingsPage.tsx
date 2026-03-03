import { useState, useEffect } from 'react';
import { isPrintAgentAvailable, printViaAgent, getPrintAgentPrinters } from '../api/printAgent';
import { openBlobInNewWindow } from '../utils/printUtils';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Card,
  CardContent,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Button,
  Alert,
} from '@mui/material';
import LocalPrintshop from '@mui/icons-material/LocalPrintshop';
import { printSettingsApi } from '../api/printSettings';
import LoadingSpinner from '../components/common/LoadingSpinner';

export default function PrintSettingsPage() {
  const queryClient = useQueryClient();
  const [defaultPrinter, setDefaultPrinter] = useState('');
  const [labelFormat, setLabelFormat] = useState<'58mm' | '80mm'>('58mm');
  const [autoPrint, setAutoPrint] = useState(true);
  const [autoPrintKiz, setAutoPrintKiz] = useState(true);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const [agentPrinters, setAgentPrinters] = useState<string[]>([]);
  const [testPrinting, setTestPrinting] = useState(false);
  const [testPrintError, setTestPrintError] = useState<string | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: ['print-settings'],
    queryFn: () => printSettingsApi.get(),
  });

  useEffect(() => {
    if (settings) {
      setDefaultPrinter(settings.default_printer ?? '');
      setLabelFormat((settings.label_format as '58mm' | '80mm') ?? '58mm');
      setAutoPrint(settings.auto_print_on_click !== false);
      setAutoPrintKiz(settings.auto_print_kiz_duplicate !== false);
    }
  }, [settings]);

  useEffect(() => {
    isPrintAgentAvailable().then((ok) => {
      setAgentAvailable(ok);
      if (ok) getPrintAgentPrinters().then(setAgentPrinters);
    });
  }, []);

  const updateMutation = useMutation({
    mutationFn: () =>
      printSettingsApi.update({
        default_printer: defaultPrinter,
        label_format: labelFormat,
        auto_print_on_click: autoPrint,
        auto_print_kiz_duplicate: autoPrintKiz,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['print-settings'] }),
  });

  const handleSave = () => updateMutation.mutate();

  const handleTestPrint = async () => {
    setTestPrintError(null);
    setTestPrinting(true);
    try {
      const blob = await printSettingsApi.getTestLabelBlob();
      if (agentAvailable) {
        const ok = await printViaAgent(blob, defaultPrinter || undefined);
        if (!ok) {
          setTestPrintError('Агент не ответил или печать не удалась. Проверьте, что агент запущен и SumatraPDF установлен.');
        }
      } else {
        openBlobInNewWindow(blob, { triggerPrint: true });
      }
    } catch (e) {
      setTestPrintError(e instanceof Error ? e.message : 'Ошибка при печати');
    } finally {
      setTestPrinting(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight={600} gutterBottom>
        Диспетчер печати
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Настройки печати этикеток через браузер
      </Typography>

      <Alert severity={agentAvailable ? 'success' : 'info'} sx={{ mb: 2 }}>
        {agentAvailable
          ? 'Агент печати подключен. Тихая печать без диалога.'
          : 'Печать выполняется через браузер. При первой печати выберите принтер в диалоге. Установите fbs-print-agent для тихой печати.'}
      </Alert>

      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <FormControl fullWidth>
                <InputLabel>Формат этикеток</InputLabel>
                <Select
                  value={labelFormat}
                  label="Формат этикеток"
                  onChange={(e) => setLabelFormat(e.target.value as '58mm' | '80mm')}
                >
                  <MenuItem value="58mm">58 мм</MenuItem>
                  <MenuItem value="80mm">80 мм</MenuItem>
                </Select>
              </FormControl>
              <FormControlLabel
                control={
                  <Switch checked={autoPrint} onChange={(e) => setAutoPrint(e.target.checked)} />
                }
                label="Автопечать 2 этикеток при клике на артикул"
              />
              <FormControlLabel
                control={
                  <Switch checked={autoPrintKiz} onChange={(e) => setAutoPrintKiz(e.target.checked)} />
                }
                label="Автопечать дубля КИЗ после скана"
              />
              {agentAvailable && agentPrinters.length > 0 ? (
                <FormControl fullWidth size="small">
                  <InputLabel>Принтер</InputLabel>
                  <Select
                    value={defaultPrinter}
                    label="Принтер"
                    onChange={(e) => setDefaultPrinter(e.target.value)}
                  >
                    <MenuItem value="">По умолчанию</MenuItem>
                    {agentPrinters.map((p) => (
                      <MenuItem key={p} value={p}>
                        {p}
                      </MenuItem>
                    ))}
                  </Select>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                    Агент печати использует выбранный принтер
                  </Typography>
                </FormControl>
              ) : (
                <TextField
                  label="Принтер"
                  value={defaultPrinter || (agentAvailable ? 'По умолчанию' : 'Выберите в диалоге печати')}
                  fullWidth
                  InputProps={{ readOnly: true }}
                  size="small"
                  helperText={agentAvailable ? 'Агент использует системный принтер по умолчанию' : 'Браузер не может задать принтер. Выберите его при первой печати.'}
                />
              )}
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Button variant="contained" onClick={handleSave} disabled={updateMutation.isPending}>
                  Сохранить
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<LocalPrintshop />}
                  onClick={handleTestPrint}
                  disabled={testPrinting}
                >
                  {testPrinting ? 'Печать…' : 'Тестовая печать'}
                </Button>
                {testPrintError && (
                  <Alert severity="error" sx={{ mt: 1 }} onClose={() => setTestPrintError(null)}>
                    {testPrintError}
                  </Alert>
                )}
              </Box>
            </Box>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
