import { useState, useRef, useEffect } from 'react';
import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  InputAdornment,
} from '@mui/material';
import Search from '@mui/icons-material/Search';
import type { Marketplace } from '../../types/api';
import type { Warehouse } from '../../types/api';

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;

export interface OrderFiltersState {
  /** '' | 'ozon' | 'wildberries' | marketplace id (number) */
  marketplace_filter: '' | 'ozon' | 'wildberries' | number;
  warehouse_id: number | '';
  status: string;
  search: string;
  sort_by: string;
  sort_desc: boolean;
  /** Заказов на странице */
  page_size: number;
}

const defaultFilters: OrderFiltersState = {
  marketplace_filter: '',
  warehouse_id: '',
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
  /** Склады доступны при любом выборе маркетплейса (Все / Ozon все / WB все / конкретный) */
}

export { defaultFilters };

export default function OrderFilters({
  filters,
  onChange,
  marketplaces,
  warehouses,
}: OrderFiltersProps) {
  const [searchInput, setSearchInput] = useState(filters.search);
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

  const handleMarketplaceChange = (value: '' | 'ozon' | 'wildberries' | number) => {
    onChange({
      ...filters,
      marketplace_filter: value,
      warehouse_id: '',
    });
  };

  const selectValue = filters.marketplace_filter === '' ? '' : String(filters.marketplace_filter);

  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center', mb: 2 }}>
      <FormControl size="small" sx={{ minWidth: 200 }}>
        <InputLabel>Маркетплейс</InputLabel>
        <Select
          value={selectValue}
          label="Маркетплейс"
          onChange={(e) => {
            const v = e.target.value;
            if (v === '' || v === 'ozon' || v === 'wildberries') {
              handleMarketplaceChange(v);
            } else {
              handleMarketplaceChange(Number(v));
            }
          }}
        >
          <MenuItem value="">Все</MenuItem>
          <MenuItem value="ozon">Ozon (все)</MenuItem>
          <MenuItem value="wildberries">WB (все)</MenuItem>
          {marketplaces.map((mp) => (
            <MenuItem key={mp.id} value={String(mp.id)}>
              {mp.name} ({mp.type})
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <FormControl size="small" sx={{ minWidth: 180 }} disabled={warehouses.length === 0}>
        <InputLabel>Склад</InputLabel>
        <Select
          value={filters.warehouse_id}
          label="Склад"
          onChange={(e) => {
            const v = e.target.value;
            onChange({ ...filters, warehouse_id: String(v) === '' ? '' : Number(v) });
          }}
        >
          <MenuItem value="">Все</MenuItem>
          {warehouses.map((w) => (
            <MenuItem key={w.id} value={w.id}>
              {w.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
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
