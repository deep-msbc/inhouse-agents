import React from 'react';
import type { DashboardConfig } from '@msbc/config-ui';
import { GridIcon, ListIcon } from '../../../assets/svg';
import Card from '../../../components/Card';

export const dashboard4config: DashboardConfig = {
  title: 'Users',
  hasSearch: true,
  createButtonProps: {
    variant: 'primary',
    text: 'Add User',
    onClick: () => {
      alert('User added Successfully!!');
    },
  },

  api: {
    url: '',
    method: 'get',
    params: {
      limit: 10,
    },
  },
  apiResponseMapper(data: any) {
    return {
      data: [],
    };
  },
  tableProps: {
    tableName: 'User',
    tableId: 'User_Table',
    columnDefs: [
      { headerName: '', checkboxSelection: true, width: 78 },
      { field: 'ID', headerName: 'ID', filter: 'true' },
      { field: 'FirstName', headerName: 'FirstName', filter: 'true' },
      { field: 'LastName', headerName: 'LastName', filter: 'true' },
      { field: 'Job_Role', headerName: 'Job_Role', filter: 'true' },
      { field: 'Salary', headerName: 'Salary', filter: 'true' },
      { field: 'city', headerName: 'City', filter: 'true' },
      { field: 'status', headerName: 'Status', filter: 'true' },
    ],
    rowSelection: 'multiple',
    //  noRowsOverlayComponent: () => React.createEment('div', null, 'No users found.')
  },
  listProps: {
    CardComponent: Card,
    layout: {
      gap: '10px',
      wrap: true,
      cardWidth: '1.5rem',
      columns: 4,
    },
    emptyComponent: 'No component found!!',
  },
  actions: [
    {
      text: 'Remove User',
      api: {
        url: '',
        method: 'post',
        autoFetch: false,
      },
    },
    {
      text: 'Edit',
      api: {
        url: '',
        method: 'patch',
        autoFetch: false,
      },
    },
    {
      text: 'Disable User',
      api: {
        url: '',
        method: 'post',
        autoFetch: false,
      },
    },
  ],
  filters: [
    { type: 'date-range', name: 'date' },
    {
      type: 'select',
      options: [],
      api: {
        url: '/api/roles',
      },
      labelKey: 'display_name',
      valueKey: 'id',
      name: 'role',
    },
  ],
  enableModeSwitch: true,
  modeSwitchProps: {
    activeColor: 'var(--color-crimson-05)',
    inactiveColor: 'var(--color-gray-07)',
    offIcon: GridIcon,
    onIcon: ListIcon,
  },
  advanceFilterProps: {
    hasAdvancedFilter: true,
    hasFilterButton: true,
    fieldInfo: [],
    fieldTypeInfo: {
      text: [
        {
          lookup_key: '',
          info: '',
        },
      ],
      bool: [
        {
          lookup_key: '',
          info: '',
        },
      ],
      date: [
        {
          lookup_key: '',
          info: '',
        },
      ],
      int: [
        {
          lookup_key: '',
          info: '',
        },
      ],
      phone: [
        {
          lookup_key: '',
          info: '',
        },
      ],
    },
    filterTitle: 'Advance Filters',
    isModalOpen: false,
    onClose: () => {},
  },
};
