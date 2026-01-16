"""
Management command to create the default tenant.
"""
from django.core.management.base import BaseCommand
from collectors.models import Tenant, Domain


class Command(BaseCommand):
    help = 'Create the default tenant for single-tenant deployment'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default='Default',
            help='Tenant name (default: Default)'
        )
        parser.add_argument(
            '--domain',
            type=str,
            default='localhost',
            help='Primary domain (default: localhost)'
        )
        parser.add_argument(
            '--schema',
            type=str,
            default='default',
            help='Schema name (default: default)'
        )

    def handle(self, *args, **options):
        name = options['name']
        domain = options['domain']
        schema = options['schema']

        # Check if tenant already exists
        if Tenant.objects.filter(schema_name=schema).exists():
            self.stdout.write(
                self.style.WARNING(f'Tenant with schema "{schema}" already exists')
            )
            tenant = Tenant.objects.get(schema_name=schema)
        else:
            # Create tenant
            tenant = Tenant.objects.create(
                name=name,
                schema_name=schema,
                is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Created tenant: {name} (schema: {schema})')
            )

        # Check if domain already exists
        if Domain.objects.filter(domain=domain).exists():
            self.stdout.write(
                self.style.WARNING(f'Domain "{domain}" already exists')
            )
        else:
            # Create primary domain
            Domain.objects.create(
                domain=domain,
                tenant=tenant,
                is_primary=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Created domain: {domain}')
            )

        # Also add common development domains
        dev_domains = ['127.0.0.1', '0.0.0.0']
        for dev_domain in dev_domains:
            if not Domain.objects.filter(domain=dev_domain).exists():
                Domain.objects.create(
                    domain=dev_domain,
                    tenant=tenant,
                    is_primary=False
                )
                self.stdout.write(
                    self.style.SUCCESS(f'Created domain: {dev_domain}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\nTenant setup complete!')
        )
        self.stdout.write(f'  Name: {tenant.name}')
        self.stdout.write(f'  Schema: {tenant.schema_name}')
        self.stdout.write(f'  Domains: {", ".join(d.domain for d in tenant.domains.all())}')
