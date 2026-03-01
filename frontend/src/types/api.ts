export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserMe {
  id: number;
  email: string;
  full_name: string;
  role: 'admin' | 'packer';
}

export interface Order {
  id: number;
  posting_number: string;
  external_id: string;
  article: string;
  product_name: string;
  quantity: number;
  warehouse_id?: number;
  warehouse_name?: string;
  warehouse_color?: string;
  product_image_url?: string;
  marketplace_id: number;
  marketplace_type?: string;
  status: string;
  is_locked_by_me?: boolean;
  is_locked_by_other?: boolean;
  assigned_to_name?: string;
  completed_at?: string;
  marketplace_created_at?: string;
  marketplace?: { is_kiz_enabled?: boolean };
  is_kiz_enabled?: boolean;
}

export interface Marketplace {
  id: number;
  type: string;
  name: string;
  is_kiz_enabled?: boolean;
  save_kiz_to_file?: boolean;
  is_active?: boolean;
  last_sync_at?: string;
}

export interface Warehouse {
  id: number;
  external_warehouse_id: string;
  name: string;
  color?: string | null;
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface PrintSettings {
  default_printer?: string;
  label_format?: '58mm' | '80mm';
  auto_print_on_click?: boolean;
  auto_print_kiz_duplicate?: boolean;
}
