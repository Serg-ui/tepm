from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, F, Q, OuterRef


class Building(models.Model):
    name = models.CharField()

    class Meta:
        verbose_name = 'Объект строительства'


class Section(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, verbose_name='Родительская секция',
                               blank=False, null=True)

    class Meta:
        verbose_name = 'Секция сметы'

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if not self.id and self.parent and getattr(self.parent, 'parent', None):
            raise ValidationError('Максимальный уровень вложенности 2')
        super().save(force_insert, force_update, using, update_fields)


class Expenditure(models.Model):
    class Types:
        WORK = 'work'
        MATERIAL = 'material'
        choices = (
            (WORK, 'Работа'),
            (MATERIAL, 'Материал'),
        )

    section = models.ForeignKey(Section, on_delete=models.PROTECT,
                                help_text='Расценка может принадлежать только той секции, у которой указан parent')
    name = models.CharField(verbose_name='Название расценки')
    type = models.CharField(verbose_name='Тип расценки', choices=Types.choices, max_length=8)
    count = models.DecimalField(verbose_name='Кол-во', max_digits=20, decimal_places=8)
    price = models.DecimalField(verbose_name='Цена за единицу', max_digits=20, decimal_places=2)

    class Meta:
        verbose_name = 'Расценка сметы'


def get_parent_sections(building_id: int) -> list[Section]:
    sections = Section.objects.prefetch_related('section').filter(
        building_id=building_id, parent__isnull=True
    ).annotate(
        budget_parent=Sum(F('section__price') * F('section__count')),
        budget_child=Sum(
            F('section__price') * F('section__count'),
            filter=Q(parent=OuterRef('pk'))
        ),
        budget_all=F('budget_parent') + F('budget_child')
    )
    return list(sections)


def get_buildings() -> list[dict]:
    """
    Ожидаемый результат функции:
    [
        {
            'id': 1,
            'works_amount': 100.00,
            'materials_amount': 200.00,
        },
        {
            'id': 2,
            'works_amount': 100.00,
            'materials_amount': 0.00,
        },
    """

    qs = Building.objects.annotate(
        works_amount=Sum(
            F('building__section__count') * F('building__section__price'),
            filter=Q(building__section__type=Expenditure.Types.WORK)
        ),
        materials_amount=Sum(
            F('building__section__count') * F('building__section__price'),
            filter=Q(building__section__type=Expenditure.Types.MATERIAL)
        )
    )
    return [{'id': b.id, 'works_amount': b.works_amount, 'materials_amount': b.materials_amount} for b in qs]


def update_with_discount(section_id: int, discount: Decimal):
    """
    @param discount: Размер скидки в процентах от Decimal(0) до Decimal(100)
    """
    if discount < 0 or discount > 100:
        raise ValidationError

    section = Section.objects.get(pk=section_id)
    discount_amount = section.price / 100 * discount
    section.price = section.price - discount_amount
    section.save()
