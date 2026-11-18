# Spendly API Documentation

Backend API for Spendly expense tracker. All endpoints return JSON.

**Base URL:** `https://your-vercel-app.vercel.app/api`

## Authentication

All protected endpoints require a JWT token in the Authorization header:

```
Authorization: Bearer <token>
```

## Endpoints

### Health Check
**GET** `/api/health`

Returns API status.

**Response:**
```json
{
  "status": "ok"
}
```

### Register
**POST** `/api/register`

Register a new user.

**Request Body:**
```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "password": "password123",
  "confirm": "password123"
}
```

**Response (201):**
```json
{
  "message": "Registration successful",
  "token": "jwt_token_here",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "display_name": "John Doe"
  }
}
```

### Login
**POST** `/api/login`

Login and get JWT token.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "message": "Login successful",
  "token": "jwt_token_here",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "display_name": "John Doe"
  }
}
```

### Dashboard
**GET** `/api/dashboard`

Get dashboard data (requires auth).

**Query Params:**
- `month` (optional): YYYY-MM format

**Response:**
```json
{
  "year": 2024,
  "month": 11,
  "month_label": "November 2024",
  "total_this_month": 5000.00,
  "total_last_month": 4500.00,
  "by_category": [
    {"category": "Food", "total": 2000.00},
    {"category": "Transport", "total": 1000.00}
  ],
  "recent": [
    {"id": 1, "amount": 500.00, "date": "2024-11-15", "note": "Lunch"}
  ]
}
```

### List Expenses
**GET** `/api/expenses`

Get user's expenses (requires auth).

**Query Params:**
- `from` (optional): YYYY-MM-DD
- `to` (optional): YYYY-MM-DD
- `category` (optional): category ID

**Response:**
```json
{
  "expenses": [
    {"id": 1, "amount": 500.00, "date": "2024-11-15", "note": "Lunch", "category_id": 1}
  ],
  "total": 5000.00,
  "categories": [{"id": 1, "name": "Food"}],
  "filters": {"from": "", "to": "", "category": ""}
}
```

### Create Expense
**POST** `/api/expenses`

Create a new expense (requires auth).

**Request Body:**
```json
{
  "amount": 500.00,
  "category_id": 1,
  "date": "2024-11-15",
  "note": "Lunch"
}
```

**Response (201):**
```json
{
  "message": "Expense created",
  "id": 1
}
```

### Get Expense
**GET** `/api/expenses/:id`

Get single expense (requires auth).

**Response:**
```json
{
  "id": 1,
  "amount": 500.00,
  "date": "2024-11-15",
  "note": "Lunch",
  "category_id": 1
}
```

### Update Expense
**PUT** `/api/expenses/:id`

Update expense (requires auth).

**Request Body:**
```json
{
  "amount": 600.00,
  "category_id": 1,
  "date": "2024-11-15",
  "note": "Updated note"
}
```

**Response:**
```json
{
  "message": "Expense updated"
}
```

### Delete Delete
**DELETE** `/api/expenses/:id`

Delete expense (requires auth).

**Response:**
```json
{
  "message": "Expense deleted"
}
```

### List Categories
**GET** `/api/categories`

Get user's categories (requires auth).

**Response:**
```json
{
  "categories": [
    {"id": 1, "name": "Food", "in_use": true},
    {"id": 2, "name": "Transport", "in_use": false}
  ]
}
```

### Create Category
**POST** `/api/categories`

Create category (requires auth).

**Request Body:**
```json
{
  "name": "Food"
}
```

**Response (201):**
```json
{
  "message": "Category created",
  "id": 1,
  "name": "Food"
}
```

### Update Category
**PUT** `/api/categories/:id`

Update category (requires auth).

**Request Body:**
```json
{
  "name": "Food & Drinks"
}
```

**Response:**
```json
{
  "message": "Category updated"
}
```

### Delete Category
**DELETE** `/api/categories/:id`

Delete category (requires auth).

**Response:**
```json
{
  "message": "Category deleted"
}
```

## Error Responses

All errors return JSON:

```json
{
  "error": "Error message here"
}
```

Status codes:
- 400: Bad Request (validation error)
- 401: Unauthorized (missing/invalid token)
- 404: Not Found
- 500: Internal Server Error
