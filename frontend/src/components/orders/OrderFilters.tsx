import { useState, useRef, useEffect } from 'react';
import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  InputAdornment,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Menu,
  Typography,
  Button,
} from '@mui/material';
import Search from '@mui/icons-material/Search';
import ArrowDropDown from '@mui/icons-material/ArrowDropDown';
import type { Marketplace } from '../../types/api';
import type { Warehouse } from '../../types/api';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;

export interface OrderFiltersState {
  /** Выбранные типы маркетплейсов: ozon, wildberries */
  marketplace_types: ('ozon' | 'wildberries')[];
  /** Выбранные ID конкретных маркетплейсов */
  marketplace_ids: number[];
  /** Выбранные ID складов */
  warehouse_ids: number[];
  status: string;
  search: string;
  sort_by: string;
  sort_desc: boolean;
  page_size: number;
}

const defaultFilters: OrderFiltersState = {
  marketplace_types: [],
  marketplace_ids: [],
  warehouse_ids: [],
  status: '',
  search: '',
  sort_by: 'marketplace_created_at',
  sort_desc: true,
  page_size: 50,
};

interface OrderFiltersProps {
  filters: OrderFiltersState;
  onChange: (filters: OrderFiltersState) => void;
  marketplaces: Marketplace[];
  warehouses: Warehouse[];
}

export { defaultFilters };

export default function OrderFilters({
  filters,
  onChange,
  marketplaces,
  warehouses,
}: OrderFiltersProps) {
  const [searchInput, setSearchInput] = useState(filters.search);
  const [mpAnchor, setMpAnchor] = useState<null | HTMLElement>(null);
  const [whAnchor, setWhAnchor] = useState<null | HTMLElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    setSearchInput(filters.search);
  }, [filters.search]);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setSearchInput(v);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      onChange({ ...filters, search: v });
    }, 300);
  };

  const toggleMarketplaceType = (t: 'ozon' | 'wildberries') => {
    const next = filters.marketplace_types.includes(t)
      ? filters.marketplace_types.filter((x) => x !== t)
      : [...filters.marketplace_types, t];
    onChange({ ...filters, marketplace_types: next });
  };

  const toggleMarketplaceId = (id: number) => {
    const next = filters.marketplace_ids.includes(id)
      ? filters.marketplace_ids.filter((x) => x !== id)
      : [...filters.marketplace_ids, id];
    onChange({ ...filters, marketplace_ids: next });
  };

  const toggleWarehouseId = (id: number) => {
    const next = filters.warehouse_ids.includes(id)
      ? filters.warehouse_ids.filter((x) => x !== id)
      : [...filters.warehouse_ids, id];
    onChange({ ...filters, warehouse_ids: next });
  };

  const hasMpFilter =
    filters.marketplace_types.length > 0 || filters.marketplace_ids.length > 0;
  const hasWhFilter = filters.warehouse_ids.length > 0;

  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center', mb: 2 }}>
      <Button
        variant="outlined"
        size="small"
        endIcon={<ArrowDropDown />}
        onClick={(e) => setMpAnchor(e.currentTarget)}
        sx={{ textTransform: 'none', minWidth: 160 }}
      >
        Маркетплейсы {hasMpFilter && `(${filters.marketplace_types.length + filters.marketplace_ids.length})`}
      </Button>
      <Menu
        anchorEl={mpAnchor}
        open={!!mpAnchor}
        onClose={() => setMpAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { maxHeight: 320 } } }}
      >
        <Box sx={{ px: 1, py: 0.5 }}>
          <FormGroup>
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={filters.marketplace_types.includes('ozon')}
                  onChange={() => toggleMarketplaceType('ozon')}
                />
              }
              label={<Typography variant="body2">Ozon (все)</Typography>}
            />
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={filters.marketplace_types.includes('wildberries')}
                  onChange={() => toggleMarketplaceType('wildberries')}
                />
              }
              label={<Typography variant="body2">WB (все)</Typography>}
            />
            {marketplaces.map((mp) => (
              <FormControlLabel
                key={mp.id}
                control={
                  <Checkbox
                    size="small"
                    checked={filters.marketplace_ids.includes(mp.id)}
                    onChange={() => toggleMarketplaceId(mp.id)}
                  />
                }
                label={<Typography variant="body2">{mp.name}</Typography>}
              />
            ))}
          </FormGroup>
        </Box>
      </Menu>
      <Button
        variant="outlined"
        size="small"
        endIcon={<ArrowDropDown />}
        onClick={(e) => setWhAnchor(e.currentTarget)}
        sx={{ textTransform: 'none', minWidth: 140 }}
      >
        Склады {hasWhFilter && `(${filters.warehouse_ids.length})`}
      </Button>
      <Menu
        anchorEl={whAnchor}
        open={!!whAnchor}
        onClose={() => setWhAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { maxHeight: 320 } } }}
      >
        <Box sx={{ px: 1, py: 0.5 }}>
          <FormGroup>
            {warehouses.map((w) => (
              <FormControlLabel
                key={w.id}
                control={
                  <Checkbox
                    size="small"
                    checked={filters.warehouse_ids.includes(w.id)}
                    onChange={() => toggleWarehouseId(w.id)}
                  />
                }
                label={<Typography variant="body2">{w.name}</Typography>}
              />
            ))}
          </FormGroup>
        </Box>
      </Menu>
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel>Статус</InputLabel>
        <Select
          value={filters.status}
          label="Статус"
          onChange={(e) => onChange({ ...filters, status: e.target.value })}
        >
          <MenuItem value="">Все</MenuItem>
          <MenuItem value="awaiting_packaging">Новые</MenuItem>
          <MenuItem value="completed">Собран</MenuItem>
        </Select>
      </FormControl>
      <TextField
        size="small"
        placeholder="Поиск: артикул, название, номер"
        value={searchInput}
        onChange={handleSearchChange}
        sx={{ width: 200 }}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <Search fontSize="small" />
            </InputAdornment>
          ),
        }}
      />
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel>Сортировка</InputLabel>
        <Select
          value={filters.sort_by}
          label="Сортировка"
          onChange={(e) => onChange({ ...filters, sort_by: e.target.value })}
        >
          <MenuItem value="marketplace_created_at">По дате</MenuItem>
          <MenuItem value="article">По артикулу</MenuItem>
          <MenuItem value="product_name">По названию</MenuItem>
        </Select>
      </FormControl>
      <FormControl size="small" sx={{ minWidth: 100 }}>
        <InputLabel>Порядок</InputLabel>
        <Select
          value={filters.sort_desc ? 'desc' : 'asc'}
          label="Порядок"
          onChange={(e) => onChange({ ...filters, sort_desc: e.target.value === 'desc' })}
        >
          <MenuItem value="desc">Убыв.</MenuItem>
          <MenuItem value="asc">Возр.</MenuItem>
        </Select>
      </FormControl>
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel>На странице</InputLabel>
        <Select
          value={filters.page_size}
          label="На странице"
          onChange={(e) => onChange({ ...filters, page_size: Number(e.target.value) })}
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <MenuItem key={n} value={n}>
              {n}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
}
