const axios = require('axios');
axios.post('http://localhost:8000/api/v1/dispatch/', {date: '2026-04-10', total_trucks: 6}).then(res => console.log(res.data)).catch(err => console.log(err.response.data));
