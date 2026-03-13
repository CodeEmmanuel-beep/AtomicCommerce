still building

app
├── api
│   └── v1
│       ├── models.py
│       └── routes
│           ├── auth.py
│           ├── cart.py
│           ├── category.py
│           ├── company_reply.py
│           ├── company_reviews.py
│           ├── customer_support.py
│           ├── membership.py
│           ├── order.py
│           ├── product.py
│           ├── product_reply.py
│           └── product_reviews.py
├── auth
│   ├── auth_jwt.py
│   └── verify_jwt.py
├── database
│   ├── async_config.py
│   ├── config.py
│   ├── d_base.py
│   └── get.py
├── exceptions.py
├── logs
│   └── logger.py
├── main.py
├── models_sql.py
├── services
│   ├── auth_service.py
│   ├── cart_service.py
│   ├── category_service.py
│   ├── company_reply_service.py
│   ├── company_reviews_service.py
│   ├── customer_support_service.py
│   ├── membership_service.py
│   ├── order_service.py
│   ├── product_reply_service.py
│   ├── product_reviews_service.py
│   └── product_service.py
└── utils
    ├── redis.py
    └── supabase_url.py
