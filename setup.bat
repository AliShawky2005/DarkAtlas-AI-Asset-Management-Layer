@echo off
mkdir app\api\routes
mkdir app\models
mkdir app\schemas
mkdir app\services\analysis
mkdir app\core
mkdir tests
mkdir alembic\versions

type nul > app\__init__.py
type nul > app\api\__init__.py
type nul > app\api\routes\__init__.py
type nul > app\models\__init__.py
type nul > app\schemas\__init__.py
type nul > app\services\__init__.py
type nul > app\services\analysis\__init__.py
type nul > app\core\__init__.py
type nul > tests\__init__.py

echo Folders created successfully!
pause